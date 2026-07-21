    const EXPORT_PART_ALIAS_MAP = {
        poi_panel_json_bundle: ['poi_panel_json'],
        poi_visual_png_bundle: ['poi_panel_png'],
        h3_panel_json_bundle: [
            'h3_metric_panel_json',
            'h3_structure_panel_json',
            'h3_typing_panel_json',
            'h3_lq_panel_json',
            'h3_gap_panel_json',
        ],
        h3_visual_png_bundle: [
            'h3_metric_panel_png',
            'h3_structure_panel_png',
            'h3_typing_panel_png',
            'h3_lq_panel_png',
            'h3_gap_panel_png',
        ],
        road_panel_json_bundle: [
            'road_connectivity_panel_json',
            'road_control_panel_json',
            'road_depth_panel_json',
            'road_choice_panel_json',
            'road_integration_panel_json',
            'road_intelligibility_panel_json',
        ],
        road_visual_png_bundle: [
            'road_connectivity_panel_png',
            'road_control_panel_png',
            'road_depth_panel_png',
            'road_choice_panel_png',
            'road_integration_panel_png',
            'road_intelligibility_panel_png',
        ],
    };

    function createAnalysisExportInitialState() {
        return {
            exportBundleGroups: [
                {
                    group_key: 'overview',
                    group_label: '概览与范围',
                    default_expanded: true,
                    children: [
                        { value: 'overview_json', label: '结果概览(JSON)' },
                        { value: 'isochrone_geojson', label: '等时圈(GEOJSON)' },
                        { value: 'map_snapshot_png', label: '地图快照(PNG)' },
                    ],
                },
                {
                    group_key: 'poi',
                    group_label: 'POI',
                    default_expanded: true,
                    children: [
                        { value: 'poi_csv', label: 'POI 表格(CSV)' },
                        { value: 'poi_geojson', label: 'POI 点位(GEOJSON)' },
                        { value: 'poi_panel_json_bundle', label: '子面板(JSON 聚合)' },
                        { value: 'poi_visual_png_bundle', label: '可视化(PNG)' },
                    ],
                },
                {
                    group_key: 'h3',
                    group_label: 'H3 分析',
                    default_expanded: true,
                    children: [
                        { value: 'h3_grid_geojson', label: 'H3 网格(GEOJSON)' },
                        { value: 'h3_summary_csv', label: 'H3 汇总(CSV)' },
                        { value: 'h3_metrics_json', label: 'H3 指标(JSON)' },
                        { value: 'h3_panel_json_bundle', label: '子面板(JSON 聚合)' },
                        { value: 'h3_visual_png_bundle', label: '可视化(PNG)' },
                    ],
                },
                {
                    group_key: 'road',
                    group_label: '路网分析',
                    default_expanded: true,
                    children: [
                        { value: 'road_syntax_geojson', label: '路网线(GEOJSON)' },
                        { value: 'road_syntax_summary_csv', label: '路网汇总(CSV)' },
                        { value: 'road_panel_json_bundle', label: '子面板(JSON 聚合)' },
                        { value: 'road_visual_png_bundle', label: '可视化(PNG)' },
                    ],
                },
                {
                    group_key: 'advanced',
                    group_label: '高级 GIS',
                    default_expanded: false,
                    children: [
                        { value: 'h3_gpkg', label: 'H3 GPKG' },
                        { value: 'h3_arcgis_package', label: 'H3 ArcGIS 包' },
                    ],
                },
            ],
            exportBundleOpenGroups: {
                overview: false,
                poi: false,
                h3: false,
                road: false,
                advanced: false,
            },
            exportBundleParts: [
                'overview_json',
                'isochrone_geojson',
                'poi_csv',
                'h3_grid_geojson',
                'h3_summary_csv',
                'map_snapshot_png',
                'poi_panel_json_bundle',
                'h3_panel_json_bundle',
            ],
            h3ExportMenuOpen: false,
            h3ExportTasksOpen: false,
            h3ExportTasks: [],
            h3ExportTaskSeq: 0,
            isExportingBundle: false,
            h3Toast: { message: '', type: 'info' },
            h3ToastTimer: null,
        };
    }

    function createAnalysisExportMethods() {
        return {
            toggleH3ExportMenu() {
                try {
                    this.h3SimplifyMenuOpen = false;
                    this.h3ExportTasksOpen = false;
                    this._normalizeExportBundleParts();
                    const nextOpen = !this.h3ExportMenuOpen;
                    if (nextOpen) {
                        this.exportBundleOpenGroups = Object.fromEntries(
                            (this.exportBundleGroups || []).map((group) => [String(group.group_key || ''), false])
                        );
                    }
                    this.h3ExportMenuOpen = nextOpen;
                } catch (err) {
                    console.error('toggle export menu failed', err);
                    this.h3ExportMenuOpen = false;
                    this._showH3ExportToast('导出面板加载失败，请刷新后重试', 'error', 2600);
                }
            },
            closeH3ExportMenu() {
                this.h3ExportMenuOpen = false;
            },
            toggleH3ExportTasks() {
                this.h3SimplifyMenuOpen = false;
                this.h3ExportMenuOpen = false;
                this.h3ExportTasksOpen = !this.h3ExportTasksOpen;
            },
            closeH3ExportTasks() {
                this.h3ExportTasksOpen = false;
            },
            handleGlobalClick(event) {
                const target = event && event.target;
                const hasClosest = !!(target && target.closest);
                const inSimplifyWrap = hasClosest && !!target.closest('.h3-simplify-wrap');
                const inExportWrap = hasClosest && !!target.closest('.h3-export-wrap');
                const inTaskPanel = hasClosest && !!target.closest('.h3-export-task-panel');
                const inTaskWrap = hasClosest && !!target.closest('.h3-task-wrap');
                if (this.h3SimplifyMenuOpen && !inSimplifyWrap) {
                    this.h3SimplifyMenuOpen = false;
                }
                if (this.h3ExportMenuOpen && !inExportWrap) {
                    this.h3ExportMenuOpen = false;
                }
                if (this.h3ExportTasksOpen && !inTaskPanel && !inTaskWrap) {
                    this.h3ExportTasksOpen = false;
                }
            },
            getH3PendingTaskCount() {
                return (this.h3ExportTasks || []).filter((task) => task.status === 'running').length;
            },
            _buildExportBundleTaskTitle() {
                return '统一导出 ZIP';
            },
            _buildExportBundleScopeLabel(selectedParts) {
                const items = Array.isArray(selectedParts) ? selectedParts : [];
                return `已选 ${items.length} 项`;
            },
            _createExportBundleTask(selectedParts) {
                this.h3ExportTaskSeq = Number(this.h3ExportTaskSeq || 0) + 1;
                const now = new Date();
                const task = {
                    id: `bundle-export-${Date.now()}-${this.h3ExportTaskSeq}`,
                    title: this._buildExportBundleTaskTitle(),
                    scope_label: this._buildExportBundleScopeLabel(selectedParts),
                    status: 'running',
                    status_label: '导出中',
                    created_at: now.toISOString(),
                    created_at_text: now.toLocaleTimeString([], { hour12: false }),
                    filename: '',
                    error: '',
                    progress_pct: 2,
                    progress_label: '准备导出参数',
                };
                this.h3ExportTasks = [task].concat(this.h3ExportTasks || []).slice(0, 20);
                return task.id;
            },
            _updateExportBundleTask(taskId, patch) {
                this.h3ExportTasks = (this.h3ExportTasks || []).map((task) => {
                    if (task.id !== taskId) return task;
                    return Object.assign({}, task, patch || {});
                });
            },
            clearH3CompletedTasks() {
                this.h3ExportTasks = (this.h3ExportTasks || []).filter((task) => task.status === 'running');
            },
            _setExportBundleTaskProgress(taskId, progressPct, label) {
                const pct = Math.max(0, Math.min(100, Number(progressPct) || 0));
                const patch = { progress_pct: pct };
                if (typeof label === 'string' && label.trim()) {
                    patch.progress_label = label.trim();
                }
                this._updateExportBundleTask(taskId, patch);
            },
            _postExportBundleWithProgress(payload, taskId) {
                return new Promise((resolve, reject) => {
                    const xhr = new XMLHttpRequest();
                    xhr.open('POST', '/api/v1/analysis/export/bundle', true);
                    xhr.responseType = 'blob';
                    xhr.setRequestHeader('Content-Type', 'application/json');

                    const requestBody = JSON.stringify(payload);
                    const requestBytes = new TextEncoder().encode(requestBody).length;

                    xhr.upload.onprogress = (event) => {
                        if (event && event.lengthComputable && event.total > 0) {
                            const ratio = event.loaded / event.total;
                            const pct = 55 + ratio * 20;
                            this._setExportBundleTaskProgress(taskId, pct, `导出进度 ${Math.round(pct)}%（上传请求体）`);
                        } else {
                            this._setExportBundleTaskProgress(taskId, 60, `上传请求体 ${this._formatBytes(requestBytes)}`);
                        }
                    };

                    xhr.onprogress = (event) => {
                        if (event && event.lengthComputable && event.total > 0) {
                            const ratio = event.loaded / event.total;
                            const pct = 80 + ratio * 18;
                            this._setExportBundleTaskProgress(taskId, pct, `导出进度 ${Math.round(pct)}%（接收文件）`);
                        } else {
                            this._setExportBundleTaskProgress(taskId, 84, '服务器正在打包 ZIP');
                        }
                    };

                    xhr.onerror = () => {
                        reject(new Error('导出请求失败'));
                    };
                    xhr.onabort = () => {
                        reject(new Error('导出请求已取消'));
                    };
                    xhr.onload = () => {
                        const disposition = xhr.getResponseHeader('content-disposition') || '';
                        const contentType = xhr.getResponseHeader('content-type') || '';
                        if (xhr.status < 200 || xhr.status >= 300) {
                            if (xhr.response instanceof Blob) {
                                xhr.response.text().then((text) => reject(new Error(text || `HTTP ${xhr.status}`))).catch(() => reject(new Error(`HTTP ${xhr.status}`)));
                                return;
                            }
                            reject(new Error(`HTTP ${xhr.status}`));
                            return;
                        }
                        resolve({
                            blob: xhr.response,
                            disposition,
                            contentType,
                        });
                    };

                    xhr.send(requestBody);
                });
            },
            _formatBytes(bytes) {
                const value = Number(bytes);
                if (!Number.isFinite(value) || value <= 0) return '0 B';
                if (value < 1024) return `${Math.round(value)} B`;
                if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
                return `${(value / (1024 * 1024)).toFixed(1)} MB`;
            },
            _showH3ExportToast(message, type = 'info', durationMs = 2200) {
                if (this.h3ToastTimer) {
                    clearTimeout(this.h3ToastTimer);
                    this.h3ToastTimer = null;
                }
                this.h3Toast = {
                    message: String(message || ''),
                    type: String(type || 'info'),
                };
                this.h3ToastTimer = setTimeout(() => {
                    this.h3Toast = { message: '', type: 'info' };
                    this.h3ToastTimer = null;
                }, Math.max(800, Number(durationMs) || 2200));
            },
            _getNormalizedExportBundleParts() {
                const allowed = new Set(this.getAllExportBundlePartValues());
                const normalized = [];
                (this.exportBundleParts || []).forEach((item) => {
                    const key = String(item || '').trim();
                    if (!key || !allowed.has(key) || normalized.includes(key)) return;
                    if (this.isExportBundlePartDisabled(key)) return;
                    normalized.push(key);
                });
                return normalized;
            },
            _resolveExportPartAliases(part) {
                const key = String(part || '').trim();
                if (!key) return [];
                if (EXPORT_PART_ALIAS_MAP[key]) return EXPORT_PART_ALIAS_MAP[key].slice();
                return [key];
            },
            _expandExportBundleParts(parts) {
                const expanded = [];
                (parts || []).forEach((item) => {
                    const resolved = this._resolveExportPartAliases(item);
                    resolved.forEach((key) => {
                        const part = String(key || '').trim();
                        if (!part || expanded.includes(part)) return;
                        if (this.getExportBundlePartDisabledReason(part)) return;
                        expanded.push(part);
                    });
                });
                return expanded;
            },
            _normalizeExportBundleParts() {
                const normalized = this._getNormalizedExportBundleParts();
                this.exportBundleParts = normalized;
                return normalized;
            },
            getAllExportBundlePartValues() {
                return (this.exportBundleGroups || [])
                    .flatMap((group) => Array.isArray(group.children) ? group.children : [])
                    .map((item) => String((item && item.value) || '').trim())
                    .filter((item) => !!item);
            },
            getSelectableExportPartsByGroup(groupKey) {
                const key = String(groupKey || '').trim();
                const group = (this.exportBundleGroups || []).find((item) => String(item.group_key || '').trim() === key);
                if (!group || !Array.isArray(group.children)) return [];
                return group.children
                    .map((item) => String((item && item.value) || '').trim())
                    .filter((part) => !!part && !this.isExportBundlePartDisabled(part));
            },
            isPanelExportPart(part) {
                const key = String(part || '').trim();
                return key === 'poi_panel_png'
                    || key === 'h3_metric_panel_png'
                    || key === 'h3_structure_panel_png'
                    || key === 'h3_typing_panel_png'
                    || key === 'h3_lq_panel_png'
                    || key === 'h3_gap_panel_png'
                    || key === 'road_connectivity_panel_png'
                    || key === 'road_control_panel_png'
                    || key === 'road_depth_panel_png'
                    || key === 'road_choice_panel_png'
                    || key === 'road_integration_panel_png'
                    || key === 'road_intelligibility_panel_png';
            },
            getSelectableExportParts() {
                const selectable = [];
                const all = this.getAllExportBundlePartValues();
                all.forEach((part) => {
                    if (selectable.includes(part)) return;
                    if (this.isExportBundlePartDisabled(part)) return;
                    selectable.push(part);
                });
                return selectable;
            },
            isExportBundleGroupExpanded(groupKey) {
                const key = String(groupKey || '').trim();
                return !!(this.exportBundleOpenGroups && this.exportBundleOpenGroups[key]);
            },
            toggleExportBundleGroupExpanded(groupKey) {
                const key = String(groupKey || '').trim();
                if (!key) return;
                this.exportBundleOpenGroups = Object.assign({}, this.exportBundleOpenGroups || {}, {
                    [key]: !this.isExportBundleGroupExpanded(key),
                });
            },
            isExportBundleGroupAllSelected(groupKey) {
                const selectable = this.getSelectableExportPartsByGroup(groupKey);
                if (!selectable.length) return false;
                const selected = new Set(this._getNormalizedExportBundleParts());
                return selectable.every((part) => selected.has(part));
            },
            isExportBundleGroupPartiallySelected(groupKey) {
                const selectable = this.getSelectableExportPartsByGroup(groupKey);
                if (!selectable.length) return false;
                const selected = new Set(this._getNormalizedExportBundleParts());
                const selectedCount = selectable.filter((part) => selected.has(part)).length;
                return selectedCount > 0 && selectedCount < selectable.length;
            },
            toggleExportBundleGroupSelection(groupKey) {
                const selectable = this.getSelectableExportPartsByGroup(groupKey);
                if (!selectable.length) {
                    this._showH3ExportToast('该分组当前没有可导出项', 'warning', 1800);
                    return;
                }
                const current = new Set(this._getNormalizedExportBundleParts());
                const allSelected = selectable.every((part) => current.has(part));
                if (allSelected) {
                    selectable.forEach((part) => current.delete(part));
                    this.exportBundleParts = Array.from(current);
                    this._showH3ExportToast('已清空该分组勾选', 'info', 1600);
                    return;
                }
                selectable.forEach((part) => current.add(part));
                this.exportBundleParts = Array.from(current);
                this._showH3ExportToast(`已勾选该分组可导出项（${selectable.length}项）`, 'info', 1800);
            },
            isAllAvailableExportPartsSelected() {
                const selectable = this.getSelectableExportParts();
                if (!selectable.length) return false;
                const selected = new Set(this._getNormalizedExportBundleParts());
                return selectable.every((part) => selected.has(part));
            },
            toggleSelectAllExportParts() {
                const selectable = this.getSelectableExportParts();
                if (!selectable.length) {
                    this.exportBundleParts = [];
                    this._showH3ExportToast('暂无可全选的导出项', 'warning');
                    return;
                }
                const selected = new Set(this._getNormalizedExportBundleParts());
                const allSelected = selectable.every((part) => selected.has(part));
                if (allSelected) {
                    this.exportBundleParts = [];
                    this._showH3ExportToast('已清空导出勾选', 'info', 1600);
                    return;
                }
                this.exportBundleParts = selectable.slice();
                this._showH3ExportToast(`已全选可导出项（${selectable.length}项）`, 'info', 1800);
            },
            hasIsochroneForExport() {
                const raw = this.lastIsochroneGeoJSON;
                if (!raw || typeof raw !== 'object') return false;
                const geometry = (raw.type === 'Feature')
                    ? raw.geometry
                    : (raw.geometry && typeof raw.geometry === 'object' ? raw.geometry : raw);
                if (!geometry || typeof geometry !== 'object') return false;
                const type = String(geometry.type || '');
                const coords = geometry.coordinates;
                if (type === 'Polygon') {
                    return Array.isArray(coords) && coords.length > 0;
                }
                if (type === 'MultiPolygon') {
                    return Array.isArray(coords) && coords.length > 0;
                }
                return false;
            },
            hasPoisForExport() {
                return Array.isArray(this.allPoisDetails) && this.allPoisDetails.length > 0;
            },
            hasH3GridForExport() {
                if (Array.isArray(this.h3AnalysisGridFeatures) && this.h3AnalysisGridFeatures.length > 0) {
                    return true;
                }
                return Array.isArray(this.h3GridFeatures) && this.h3GridFeatures.length > 0;
            },
            hasH3AnalysisForExport() {
                return Array.isArray(this.h3AnalysisGridFeatures)
                    && this.h3AnalysisGridFeatures.length > 0
                    && !!this.h3AnalysisSummary;
            },
            hasRoadSyntaxForExport() {
                return Array.isArray(this.roadSyntaxRoadFeatures) && this.roadSyntaxRoadFeatures.length > 0;
            },
            hasRoadSyntaxSummaryForExport() {
                return !!this.roadSyntaxSummary;
            },
            hasAnyResultForExport() {
                return this.hasIsochroneForExport()
                    || this.hasPoisForExport()
                    || this.hasH3GridForExport()
                    || this.hasRoadSyntaxForExport()
                    || this.hasRoadSyntaxSummaryForExport();
            },
            getExportBundlePartDisabledReason(part) {
                const key = String(part || '').trim();
                if (!key) return '不可用导出项';
                if (EXPORT_PART_ALIAS_MAP[key]) {
                    const reasons = this._resolveExportPartAliases(key)
                        .map((item) => this.getExportBundlePartDisabledReason(item))
                        .filter((reason) => !!reason);
                    return reasons.length >= this._resolveExportPartAliases(key).length
                        ? (reasons[0] || '暂无可导出结果')
                        : '';
                }
                if (key === 'overview_json') return '';
                if (key === 'map_snapshot_png') return '';
                if (key === 'frontend_charts_png') return this.hasAnyResultForExport() ? '' : '请先生成至少一类分析结果';
                if (key === 'isochrone_geojson') return this.hasIsochroneForExport() ? '' : '请先生成等时圈结果';
                if (key === 'poi_csv' || key === 'poi_geojson') return this.hasPoisForExport() ? '' : '请先完成 POI 抓取';
                if (key === 'poi_panel_png') return this.hasPoisForExport() ? '' : '请先完成 POI 抓取';
                if (key === 'poi_panel_json') return this.hasPoisForExport() ? '' : '请先完成 POI 抓取';
                if (key === 'h3_grid_geojson' || key === 'h3_summary_csv') return this.hasH3GridForExport() ? '' : '请先生成 H3 网格';
                if (key === 'h3_metrics_json') return this.hasH3AnalysisForExport() ? '' : '请先完成 H3 指标计算';
                if (key === 'h3_metric_panel_png' || key === 'h3_structure_panel_png' || key === 'h3_typing_panel_png' || key === 'h3_lq_panel_png' || key === 'h3_gap_panel_png') {
                    return this.hasH3AnalysisForExport() ? '' : '请先完成 H3 指标计算';
                }
                if (key === 'h3_metric_panel_json' || key === 'h3_structure_panel_json' || key === 'h3_typing_panel_json' || key === 'h3_lq_panel_json' || key === 'h3_gap_panel_json') {
                    return this.hasH3AnalysisForExport() ? '' : '请先完成 H3 指标计算';
                }
                if (key === 'h3_gpkg' || key === 'h3_arcgis_package') return this.hasH3GridForExport() ? '' : '请先生成 H3 网格';
                if (key === 'road_syntax_geojson') return this.hasRoadSyntaxForExport() ? '' : '请先完成路网分析';
                if (key === 'road_syntax_summary_csv') return this.hasRoadSyntaxSummaryForExport() ? '' : '请先完成路网分析';
                if (
                    key === 'road_connectivity_panel_png'
                    || key === 'road_control_panel_png'
                    || key === 'road_depth_panel_png'
                    || key === 'road_choice_panel_png'
                    || key === 'road_integration_panel_png'
                    || key === 'road_intelligibility_panel_png'
                ) {
                    return this.hasRoadSyntaxSummaryForExport() ? '' : '请先完成路网分析';
                }
                if (
                    key === 'road_connectivity_panel_json'
                    || key === 'road_control_panel_json'
                    || key === 'road_depth_panel_json'
                    || key === 'road_choice_panel_json'
                    || key === 'road_integration_panel_json'
                    || key === 'road_intelligibility_panel_json'
                ) {
                    return this.hasRoadSyntaxSummaryForExport() ? '' : '请先完成路网分析';
                }
                if (key === 'ai_report_json' || key === 'ai_facts_json' || key === 'ai_context_md') {
                    return this.hasAnyResultForExport() ? '' : '请先生成至少一类分析结果';
                }
                return '';
            },
            isExportBundlePartDisabled(part) {
                return !!this.getExportBundlePartDisabledReason(part);
            },
            getExportBundlePartHint(part) {
                const key = String(part || '').trim();
                const reason = this.getExportBundlePartDisabledReason(key);
                if (reason) return reason;
                if (key === 'overview_json') return '中心点、模式、时间、数据源等总览信息';
                if (key === 'map_snapshot_png') return '按当前地图视图生成一张截图';
                if (key === 'frontend_charts_png') return '导出全局统计图（分类、分布、散点等）PNG';
                if (key === 'poi_panel_json_bundle') return 'POI 子面板结构化结果(JSON 聚合)';
                if (key === 'poi_visual_png_bundle') return 'POI 结果可视化面板(PNG)';
                if (key === 'h3_panel_json_bundle') return 'H3 子面板结构化结果(JSON 聚合)';
                if (key === 'h3_visual_png_bundle') return 'H3 结果可视化面板(PNG)';
                if (key === 'road_panel_json_bundle') return '路网子面板结构化结果(JSON 聚合)';
                if (key === 'road_visual_png_bundle') return '路网结果可视化面板(PNG)';
                if (key === 'isochrone_geojson') return '当前等时圈范围 GeoJSON';
                if (key === 'poi_csv') return 'POI 明细表';
                if (key === 'poi_geojson') return 'POI 空间点位';
                if (key === 'poi_panel_png') return '当前 POI 结果子面板 PNG';
                if (key === 'poi_panel_json') return 'POI 子面板对应的结构化结果(JSON)';
                if (key === 'h3_grid_geojson') return 'H3 网格面';
                if (key === 'h3_summary_csv') return 'H3 每格分析结果';
                if (key === 'h3_metrics_json') return 'H3 汇总指标与图表数据';
                if (key === 'h3_metric_panel_png') return 'H3 密度场结果子面板';
                if (key === 'h3_structure_panel_png') return 'H3 结构图结果子面板';
                if (key === 'h3_typing_panel_png') return 'H3 功能混合度结果子面板';
                if (key === 'h3_lq_panel_png') return 'H3 区位商优势结果子面板';
                if (key === 'h3_gap_panel_png') return 'H3 缺口评估结果子面板';
                if (key === 'h3_metric_panel_json') return 'H3 密度场子面板结构化结果(JSON)';
                if (key === 'h3_structure_panel_json') return 'H3 结构图子面板结构化结果(JSON)';
                if (key === 'h3_typing_panel_json') return 'H3 功能混合度子面板结构化结果(JSON)';
                if (key === 'h3_lq_panel_json') return 'H3 区位商优势子面板结构化结果(JSON)';
                if (key === 'h3_gap_panel_json') return 'H3 缺口评估子面板结构化结果(JSON)';
                if (key === 'road_syntax_geojson') return '路网结果线';
                if (key === 'road_syntax_summary_csv') return '路网汇总指标';
                if (key === 'road_connectivity_panel_png') return '路网连接度结果子面板';
                if (key === 'road_control_panel_png') return '路网控制值结果子面板';
                if (key === 'road_depth_panel_png') return '路网深度值结果子面板';
                if (key === 'road_choice_panel_png') return '路网选择度结果子面板';
                if (key === 'road_integration_panel_png') return '路网整合度结果子面板';
                if (key === 'road_intelligibility_panel_png') return '路网可理解度结果子面板';
                if (key === 'road_connectivity_panel_json') return '路网连接度子面板结构化结果(JSON)';
                if (key === 'road_control_panel_json') return '路网控制值子面板结构化结果(JSON)';
                if (key === 'road_depth_panel_json') return '路网深度值子面板结构化结果(JSON)';
                if (key === 'road_choice_panel_json') return '路网选择度子面板结构化结果(JSON)';
                if (key === 'road_integration_panel_json') return '路网整合度子面板结构化结果(JSON)';
                if (key === 'road_intelligibility_panel_json') return '路网可理解度子面板结构化结果(JSON)';
                if (key === 'ai_report_json') return '供 AI 使用的结构化综合报告（左侧结果汇总）';
                if (key === 'ai_facts_json') return '供 AI 直接读取的核心指标事实表';
                if (key === 'ai_context_md') return '供 AI 使用的分析口径与解释边界';
                if (key === 'h3_gpkg') return 'H3 GeoPackage 专业格式';
                if (key === 'h3_arcgis_package') return 'H3 ArcGIS 专业包';
                return '';
            },
            getExportBundleHint() {
                return '支持一次勾选多个导出项，统一打包为 ZIP 下载。';
            },
            _getFilenameFromContentDisposition(disposition) {
                const text = String(disposition || '');
                const utf8Match = text.match(/filename\*=UTF-8''([^;]+)/i);
                if (utf8Match && utf8Match[1]) {
                    try { return decodeURIComponent(utf8Match[1]); } catch (_) { return utf8Match[1]; }
                }
                const quotedMatch = text.match(/filename="([^"]+)"/i);
                if (quotedMatch && quotedMatch[1]) return quotedMatch[1];
                const plainMatch = text.match(/filename=([^;]+)/i);
                if (plainMatch && plainMatch[1]) return plainMatch[1].trim();
                return '';
            },
            _downloadBlobFile(blob, filename) {
                const url = URL.createObjectURL(blob);
                const link = document.createElement('a');
                link.href = url;
                link.download = filename || 'analysis_export.zip';
                document.body.appendChild(link);
                link.click();
                document.body.removeChild(link);
                window.setTimeout(() => URL.revokeObjectURL(url), 1000);
            },
            _buildExportCountBadgeGridHtml(items, columns = 2) {
                const safeItems = Array.isArray(items) ? items : [];
                if (!safeItems.length) return '';
                const cols = Math.max(1, Number(columns) || 1);
                const rows = safeItems.map((item) => {
                    const label = this._escapeExportHtml(item && item.label);
                    const value = this._escapeExportHtml(item && item.value);
                    const smallClass = item && item.small ? ' export-metric-card--small' : '';
                    return `<div class="export-metric-card${smallClass}"><div class="export-metric-card__label">${label}</div><div class="export-metric-card__value">${value}</div></div>`;
                }).join('');
                return `<div class="export-metric-grid" style="grid-template-columns:repeat(${cols}, minmax(0, 1fr));">${rows}</div>`;
            },
            _createExportPanelHost(title) {
                const panel = document.createElement('section');
                panel.className = 'panel-card export-panel-host';
                panel.style.cssText = 'width:980px;background:#fff;border-radius:18px;border:1px solid #e5e7eb;padding:20px 22px;box-sizing:border-box;color:#0f172a;font-family:"PingFang SC","Microsoft YaHei",sans-serif;';
                const heading = document.createElement('div');
                heading.style.cssText = 'font-size:20px;font-weight:700;color:#111827;margin-bottom:14px;';
                heading.textContent = String(title || '分析面板');
                const body = document.createElement('div');
                body.className = 'export-panel-host__body';
                body.style.cssText = 'display:flex;flex-direction:column;gap:14px;';
                panel.appendChild(heading);
                panel.appendChild(body);
                return { panel, body };
            },
            _appendExportHtml(container, html) {
                if (!container || !html) return;
                const wrapper = document.createElement('div');
                wrapper.innerHTML = html;
                while (wrapper.firstChild) {
                    container.appendChild(wrapper.firstChild);
                }
            },
            _escapeExportHtml(value) {
                return String(value == null ? '' : value)
                    .replace(/&/g, '&amp;')
                    .replace(/</g, '&lt;')
                    .replace(/>/g, '&gt;')
                    .replace(/"/g, '&quot;')
                    .replace(/'/g, '&#39;');
            },
            _formatExportNumber(value, decimals = 2) {
                const num = Number(value);
                if (!Number.isFinite(num)) return '-';
                return num.toFixed(Math.max(0, Number(decimals) || 0));
            },
            _formatExportPercent(value, decimals = 1) {
                const num = Number(value);
                if (!Number.isFinite(num)) return '-';
                return `${num.toFixed(Math.max(0, Number(decimals) || 0))}%`;
            },
            _buildExportLegendHtml(items) {
                const safeItems = Array.isArray(items)
                    ? items
                    : ((items && Array.isArray(items.items)) ? items.items : []);
                if (!safeItems.length) return '';
                const cells = safeItems.map((item) => {
                    const color = this._escapeExportHtml(item && item.color);
                    const label = this._escapeExportHtml(item && item.label);
                    return `<div style="display:flex;align-items:center;gap:8px;"><span style="display:inline-block;width:12px;height:12px;border-radius:4px;background:${color};border:1px solid rgba(15,23,42,0.08);"></span><span style="font-size:13px;color:#475569;">${label}</span></div>`;
                }).join('');
                return `<div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px 14px;padding:12px 14px;border-radius:12px;background:#f8fafc;border:1px solid #e5e7eb;">${cells}</div>`;
            },
            _buildMetricLegend(metricBreaksOrLegend, metricKey = 'density') {
                const normalizeItems = (input) => {
                    const raw = Array.isArray(input)
                        ? input
                        : ((input && Array.isArray(input.items)) ? input.items : []);
                    return raw
                        .map((item) => {
                            const color = String((item && item.color) || '').trim();
                            const label = String((item && item.label) || '').trim();
                            if (!color || !label) return null;
                            return { color, label };
                        })
                        .filter((item) => !!item);
                };

                const direct = normalizeItems(metricBreaksOrLegend);
                if (direct.length) return direct;

                const fromPanelLegend = normalizeItems(this.h3Legend);
                if (fromPanelLegend.length) return fromPanelLegend;

                const source = (metricBreaksOrLegend && typeof metricBreaksOrLegend === 'object')
                    ? metricBreaksOrLegend
                    : {};
                const spec = typeof this._getMetricSpec === 'function'
                    ? (this._getMetricSpec(metricKey) || {})
                    : {};

                const palette = (Array.isArray(source.palette) && source.palette.length
                    ? source.palette
                    : (Array.isArray(spec.palette) ? spec.palette : []))
                    .map((c) => String(c || '').trim())
                    .filter((c) => !!c);
                if (!palette.length) return [];

                const formatValue = (value) => {
                    if (typeof this._formatLegendValue === 'function') {
                        return this._formatLegendValue(value, metricKey);
                    }
                    const num = Number(value);
                    if (!Number.isFinite(num)) return '-';
                    if (metricKey === 'entropy') return num.toFixed(2);
                    const abs = Math.abs(num);
                    if (abs >= 100) return num.toFixed(0);
                    if (abs >= 10) return num.toFixed(1);
                    return num.toFixed(2);
                };

                const breaks = (Array.isArray(source.breaks) ? source.breaks : [])
                    .map((v) => Number(v))
                    .filter((v) => Number.isFinite(v));

                if (!breaks.length) {
                    const min = Number(source.min);
                    const max = Number(source.max);
                    if (Number.isFinite(min) && Number.isFinite(max)) {
                        return [{
                            color: palette[palette.length - 1],
                            label: `${formatValue(min)} ~ ${formatValue(max)}`,
                        }];
                    }
                    return [{ color: palette[0], label: '无有效数据' }];
                }

                const classCount = Math.min(palette.length, breaks.length + 1);
                const items = [];
                for (let i = 0; i < classCount; i += 1) {
                    let label = '';
                    if (i === 0) {
                        label = `≤ ${formatValue(breaks[0])}`;
                    } else if (i === classCount - 1) {
                        label = `> ${formatValue(breaks[breaks.length - 1])}`;
                    } else {
                        label = `${formatValue(breaks[i - 1])} ~ ${formatValue(breaks[i])}`;
                    }
                    items.push({ color: palette[i], label });
                }
                return items;
            },
            _buildExportDecisionCardsHtml(items) {
                return this._buildExportCountBadgeGridHtml(items, 3);
            },
            _buildExportTableHtml(headers, rows, options = {}) {
                const safeHeaders = Array.isArray(headers) ? headers : [];
                const safeRows = Array.isArray(rows) ? rows : [];
                if (!safeHeaders.length) return '';
                const headHtml = safeHeaders.map((item) => `<th style="text-align:left;padding:10px 12px;border-bottom:1px solid #e5e7eb;font-size:12px;color:#64748b;font-weight:600;">${this._escapeExportHtml(item)}</th>`).join('');
                const bodyHtml = safeRows.length
                    ? safeRows.map((row) => `<tr>${(Array.isArray(row) ? row : []).map((cell) => `<td style="padding:10px 12px;border-bottom:1px solid #eef2f7;font-size:13px;color:#0f172a;vertical-align:top;">${this._escapeExportHtml(cell)}</td>`).join('')}</tr>`).join('')
                    : `<tr><td colspan="${safeHeaders.length}" style="padding:14px 12px;color:#94a3b8;font-size:13px;">暂无数据</td></tr>`;
                const marginTop = this._escapeExportHtml(options.marginTop || '8px');
                return `<div style="margin-top:${marginTop};border:1px solid #e5e7eb;border-radius:12px;overflow:hidden;"><table style="width:100%;border-collapse:collapse;background:#fff;"><thead style="background:#f8fafc;"><tr>${headHtml}</tr></thead><tbody>${bodyHtml}</tbody></table></div>`;
            },
            async _renderExportChartDataUrl(option, width = 980, height = 520) {
                if (!window.echarts || !option) return '';
                const host = document.createElement('div');
                host.style.cssText = `position:fixed;left:-20000px;top:0;width:${Math.max(320, Number(width) || 980)}px;height:${Math.max(240, Number(height) || 520)}px;background:#ffffff;z-index:-1;pointer-events:none;`;
                document.body.appendChild(host);
                let chart = null;
                try {
                    chart = echarts.init(host, null, { renderer: 'canvas' });
                    chart.setOption(option, true);
                    await this.$nextTick();
                    await this._waitForUiPaint();
                    return chart.getDataURL({ type: 'png', pixelRatio: 2, backgroundColor: '#ffffff' }) || '';
                } catch (err) {
                    console.warn('render export chart failed', err);
                    return '';
                } finally {
                    if (chart) chart.dispose();
                    if (host.parentNode) host.parentNode.removeChild(host);
                }
            },
            _getChartDataUrl(instance, backgroundColor = '#ffffff') {
                if (!instance || typeof instance.getDataURL !== 'function') return '';
                try {
                    return instance.getDataURL({ type: 'png', pixelRatio: 2, backgroundColor }) || '';
                } catch (_) {
                    return '';
                }
            },
            _cloneChartOptionForExport(instance) {
                if (!instance || typeof instance.getOption !== 'function') return null;
                try {
                    const option = instance.getOption();
                    if (!option || typeof option !== 'object') return null;
                    return JSON.parse(JSON.stringify(option));
                } catch (_) {
                    return null;
                }
            },
            _buildPoiChartExportOption() {
                return this._cloneChartOptionForExport(this.poiChart);
            },
            _buildH3CategoryChartExportOption() {
                return this._cloneChartOptionForExport(this.h3CategoryChart);
            },
            _buildH3DensityChartExportOption() {
                return this._cloneChartOptionForExport(this.h3DensityChart);
            },
            _buildH3StructureChartExportOption() {
                return this._cloneChartOptionForExport(this.h3StructureChart);
            },
            _buildH3LqChartExportOption() {
                return this._cloneChartOptionForExport(this.h3LqChart);
            },
            _buildH3GapChartExportOption() {
                return this._cloneChartOptionForExport(this.h3GapChart);
            },
            _buildRoadSyntaxScatterChartExportOption() {
                return this._cloneChartOptionForExport(this.roadSyntaxScatterChart);
            },
            _buildH3MetricLegendForExport() {
                const summary = this.h3AnalysisSummary || {};
                return this._buildMetricLegend(summary.metric_breaks || this.h3Legend || null, this.h3MetricView);
            },
            _buildH3StructureLegendForExport() {
                const summary = this.h3AnalysisSummary || {};
                if (this.h3StructureFillMode === 'lisa_i') {
                    if (typeof this._buildLisaLegend === 'function') {
                        return this._buildLisaLegend(summary.lisa_render_meta);
                    }
                    return [];
                }
                if (typeof this._buildGiLegend === 'function') {
                    return this._buildGiLegend(summary.gi_render_meta);
                }
                return [];
            },
            _buildH3TypingLegendHtml() {
                const legendItems = [
                    { color: '#1d4ed8', label: '高密高混合：成熟复合中心' },
                    { color: '#f97316', label: '高密低混合：单核主导片区' },
                    { color: '#22c55e', label: '低密高混合：潜力培育片区' },
                    { color: '#94a3b8', label: '低密低混合：薄弱提升片区' },
                ];
                const legendHtml = this._buildExportLegendHtml(legendItems);
                const confidenceHtml = `
                    <div class="panel-placeholder">
                        可信度口径：POI ≥ 10 为高，5~9 为中，<5 为低。
                    </div>
                `;
                return `${legendHtml}${confidenceHtml}`;
            },
            async _waitForExportImages(root) {
                const images = Array.from((root && root.querySelectorAll) ? root.querySelectorAll('img') : []);
                if (!images.length) return;
                await Promise.all(images.map((img) => {
                    if (img.complete && img.naturalWidth > 0) return Promise.resolve();
                    return new Promise((resolve) => {
                        const done = () => {
                            img.removeEventListener('load', done);
                            img.removeEventListener('error', done);
                            resolve();
                        };
                        img.addEventListener('load', done, { once: true });
                        img.addEventListener('error', done, { once: true });
                    });
                }));
            },
            async _captureExportPanelNode(node) {
                if (typeof html2canvas !== 'function' || !node) return null;
                const wrapper = document.createElement('div');
                wrapper.style.cssText = 'position:fixed;left:-20000px;top:0;padding:16px;background:#ffffff;z-index:-1;pointer-events:none;';
                wrapper.appendChild(node);
                document.body.appendChild(wrapper);
                try {
                    await this.$nextTick();
                    await this._waitForUiPaint();
                    await this._waitForExportImages(wrapper);
                    const canvas = await html2canvas(node, {
                        useCORS: true,
                        backgroundColor: '#ffffff',
                        scale: 2,
                        logging: false,
                    });
                    if (!canvas || typeof canvas.toDataURL !== 'function') return null;
                    const dataUrl = canvas.toDataURL('image/png');
                    return (typeof dataUrl === 'string' && dataUrl.startsWith('data:image/png;base64,')) ? dataUrl : null;
                } catch (err) {
                    console.warn('capture export panel failed', err);
                    return null;
                } finally {
                    if (wrapper && wrapper.parentNode) wrapper.parentNode.removeChild(wrapper);
                }
            },
            _sleepForExport(ms = 0) {
                const waitMs = Math.max(0, Number(ms) || 0);
                return new Promise((resolve) => window.setTimeout(resolve, waitMs));
            },
            async _captureMapSnapshotBase64() {
                if (typeof html2canvas !== 'function') return null;
                const mapContainer = document.getElementById('container');
                if (!mapContainer) return null;
                try {
                    await this.$nextTick();
                    await this._waitForUiPaint();
                    const canvas = await html2canvas(mapContainer, {
                        useCORS: true,
                        backgroundColor: '#ffffff',
                        scale: 2,
                        logging: false,
                    });
                    if (!canvas || typeof canvas.toDataURL !== 'function') return null;
                    const dataUrl = canvas.toDataURL('image/png');
                    return (typeof dataUrl === 'string' && dataUrl.startsWith('data:image/png;base64,')) ? dataUrl : null;
                } catch (err) {
                    console.warn('capture map snapshot failed', err);
                    return null;
                }
            },
            async _buildPoiPanelExportNode() {
                const { panel, body } = this._createExportPanelHost('POI 分类');
                const totalCount = Array.isArray(this.allPoisDetails) ? this.allPoisDetails.length : 0;
                this._appendExportHtml(body, this._buildExportCountBadgeGridHtml([
                    { label: '总数', value: totalCount },
                ], 1));
                const filtersContainer = document.getElementById('filtersContainer');
                if (filtersContainer) {
                    const filtersClone = filtersContainer.cloneNode(true);
                    body.appendChild(filtersClone);
                }
                return panel;
            },
            async _buildH3MetricPanelExportNode() {
                const summary = this.h3AnalysisSummary || null;
                if (!summary) return null;
                const categoryDataUrl = await this._renderExportChartDataUrl(this._buildH3CategoryChartExportOption(), 980, 520);
                const densityDataUrl = await this._renderExportChartDataUrl(this._buildH3DensityChartExportOption(), 980, 560);
                const { panel, body } = this._createExportPanelHost('H3 分析 · 密度场');
                this._appendExportHtml(body, this._buildExportCountBadgeGridHtml([
                    { label: 'POI总数', value: summary.poi_count },
                    { label: '平均密度', value: this._formatExportNumber(summary.avg_density_poi_per_km2, 2) },
                    { label: '平均熵', value: this._formatExportNumber(summary.avg_local_entropy, 3) },
                    { label: '网格数', value: summary.grid_count ?? this.h3GridCount },
                    { label: 'Gi*有效格', value: (summary.gi_z_stats && summary.gi_z_stats.count) ?? 0 },
                    { label: 'LISA有效格', value: (summary.lisa_i_stats && summary.lisa_i_stats.count) ?? 0 },
                ], 2));
                this._appendExportHtml(body, '<div class="h3-analysis-hint">看密度、混合度和邻域差值，优先找“高密且邻域为正”的连续片区。</div>');
                this._appendExportHtml(body, this._buildExportLegendHtml(this._buildH3MetricLegendForExport()));
                if (categoryDataUrl) {
                    this._appendExportHtml(body, `<div style="margin-top:8px;"><img src="${categoryDataUrl}" alt="H3 分类分布图" style="display:block;width:100%;border-radius:10px;border:1px solid #e5e7eb;background:#fff;" /></div>`);
                }
                if (densityDataUrl) {
                    this._appendExportHtml(body, `<div><img src="${densityDataUrl}" alt="H3 密度分布图" style="display:block;width:100%;border-radius:10px;border:1px solid #e5e7eb;background:#fff;" /></div>`);
                }
                return panel;
            },
            async _buildH3StructurePanelExportNode() {
                const summary = this.h3AnalysisSummary || null;
                const derived = this.h3DerivedStats && this.h3DerivedStats.structureSummary;
                if (!summary || !derived) return null;
                const chartDataUrl = await this._renderExportChartDataUrl(this._buildH3StructureChartExportOption(), 980, 520);
                const rows = (derived.rows || []).slice(0, Math.max(1, this.h3DecisionTopN)).map((row) => ([
                    this.shortH3Id(row.h3_id),
                    row.gi_star_z_score === null ? '-' : this._formatExportNumber(row.gi_star_z_score, 2),
                    row.lisa_i === null ? '-' : this._formatExportNumber(row.lisa_i, 2),
                    Number.isFinite(row.structure_signal) ? this._formatExportNumber(row.structure_signal, 2) : '-',
                    row.density === null ? '-' : this._formatExportNumber(row.density, 2),
                ]));
                const reportMap = (typeof this.getArcgisReportMap === 'function') ? this.getArcgisReportMap() : null;
                const reportMapSrc = reportMap && typeof this.getArcgisReportMapSrc === 'function' ? this.getArcgisReportMapSrc() : '';
                const reportMapTitle = reportMap && typeof this.getArcgisReportMapTitle === 'function'
                    ? this.getArcgisReportMapTitle()
                    : 'ArcGIS 结构专题图';
                const { panel, body } = this._createExportPanelHost('H3 分析 · 结构图');
                this._appendExportHtml(body, '<div class="h3-analysis-hint">结构图口径：仅使用 ArcGIS 连续字段。Gi* 使用 GiZScore；LISA 使用 LMiIndex；网格边框统一蓝色。</div>');
                this._appendExportHtml(body, this._buildExportCountBadgeGridHtml([
                    { label: '莫兰指数', value: summary.global_moran_i_density ?? 'N/A' },
                    { label: '莫兰z值', value: summary.global_moran_z_score ?? 'N/A' },
                    { label: this.h3StructureFillMode === 'gi_z' ? 'Gi*有效格' : 'LISA有效格', value: this.h3StructureFillMode === 'gi_z' ? ((summary.gi_z_stats && summary.gi_z_stats.count) ?? 0) : ((summary.lisa_i_stats && summary.lisa_i_stats.count) ?? 0) },
                    { label: '引擎', value: (summary.analysis_engine || 'pysal').toUpperCase() },
                ], 2));
                if (derived.lisaRenderMeta && derived.lisaRenderMeta.degraded) {
                    this._appendExportHtml(body, `<div class="h3-analysis-hint">${this._escapeExportHtml(derived.lisaRenderMeta.message || 'LMiIndex方差不足')}</div>`);
                }
                if (summary.arcgis_status) {
                    this._appendExportHtml(body, `<div class="h3-analysis-hint">${this._escapeExportHtml(summary.arcgis_status)}</div>`);
                }
                if (reportMapSrc) {
                    this._appendExportHtml(body, `
                        <div style="border:1px solid #eef1f4;border-radius:10px;padding:8px;background:#fafbfc;">
                            <div style="font-size:12px;color:#374151;font-weight:600;margin-bottom:6px;">${this._escapeExportHtml(reportMapTitle)}</div>
                            <img src="${reportMapSrc}" alt="ArcGIS结构专题图" style="width:100%;border-radius:8px;border:1px solid #dbe2ea;" />
                        </div>
                    `);
                } else {
                    this._appendExportHtml(body, '<div class="h3-analysis-hint">ArcGIS 专题图当前不可用，未使用本地图片替代。</div>');
                }
                this._appendExportHtml(body, this._buildExportLegendHtml(this._buildH3StructureLegendForExport()));
                this._appendExportHtml(body, this._buildExportDecisionCardsHtml([
                    { label: 'Gi* 均值', value: derived.giZStats.mean === null ? '-' : this._formatExportNumber(derived.giZStats.mean, 2) },
                    { label: 'Gi* 中位数', value: derived.giZStats.p50 === null ? '-' : this._formatExportNumber(derived.giZStats.p50, 2) },
                    { label: 'LISA 正值占比', value: derived.lisaPositivePct === null ? '-' : this._formatExportPercent(derived.lisaPositivePct, 1) },
                    { label: 'LISA 负值占比', value: derived.lisaNegativePct === null ? '-' : this._formatExportPercent(derived.lisaNegativePct, 1) },
                ]));
                if (chartDataUrl) {
                    this._appendExportHtml(body, `<div><img src="${chartDataUrl}" alt="结构连续指标图" style="display:block;width:100%;border-radius:10px;border:1px solid #e5e7eb;background:#fff;" /></div>`);
                }
                this._appendExportHtml(body, this._buildExportTableHtml(['H3', 'Gi*z', 'LISA I', '结构信号', '密度'], rows));
                return panel;
            },
            async _buildH3TypingPanelExportNode() {
                const typing = this.h3DerivedStats && this.h3DerivedStats.typingSummary;
                if (!typing) return null;
                const rows = (typing.rows || []).slice(0, Math.max(1, this.h3DecisionTopN)).map((row) => ([
                    this.shortH3Id(row.h3_id),
                    row.poi_count,
                    this._formatExportNumber(row.density, 2),
                    row.entropy_norm === null ? '-' : this._formatExportNumber(row.entropy_norm, 2),
                    (row.confidence && row.confidence.label) || '低',
                    row.type_label || '-',
                ]));
                const { panel, body } = this._createExportPanelHost('H3 诊断 · 功能混合度');
                this._appendExportHtml(body, '<div class="h3-analysis-hint">看四象限结构：高密高混合偏成熟，高密低混合偏单核，低密高混合偏潜力，低密低混合偏薄弱；同时参考可信度。</div>');
                this._appendExportHtml(body, this._buildH3TypingLegendHtml());
                this._appendExportHtml(body, this._buildExportDecisionCardsHtml([
                    { label: '机会网格数', value: typing.opportunityCount },
                    { label: '最高密度', value: this._formatExportNumber(typing.maxDensity, 2) },
                    { label: '建议动作', value: typing.recommendation || '-', small: true },
                ]));
                this._appendExportHtml(body, this._buildExportTableHtml(['H3', 'POI', '密度', '熵', '可信度', '分型'], rows, { marginTop: '0' }));
                return panel;
            },
            async _buildH3LqPanelExportNode() {
                const summary = this.h3DerivedStats && this.h3DerivedStats.lqSummary;
                if (!summary) return null;
                const chartDataUrl = await this._renderExportChartDataUrl(this._buildH3LqChartExportOption(), 980, 520);
                const rows = (summary.rows || []).slice(0, Math.max(1, this.h3DecisionTopN)).map((row) => ([
                    this.shortH3Id(row.h3_id),
                    row.poi_count,
                    this._formatExportNumber(row.density, 2),
                    row.entropy_norm === null ? '-' : this._formatExportNumber(row.entropy_norm, 2),
                    (row.confidence && row.confidence.label) || '低',
                    Number.isFinite(row.structure_signal) ? this._formatExportNumber(row.structure_signal, 2) : '-',
                    row.lq_target === null ? '-' : this._formatExportNumber(row.lq_target, 2),
                ]));
                const { panel, body } = this._createExportPanelHost('H3 诊断 · 区位商优势');
                this._appendExportHtml(body, '<div class="h3-analysis-hint">看目标业态相对本分析区是否更强：大于1偏强，小于1偏弱；已做小样本平滑。</div>');
                this._appendExportHtml(body, this._buildExportDecisionCardsHtml([
                    { label: '优势网格数', value: summary.opportunityCount },
                    { label: '最高优势值', value: this._formatExportNumber(summary.maxLq, 2) },
                    { label: '建议业态', value: summary.recommendation || '-', small: true },
                ]));
                if (chartDataUrl) {
                    this._appendExportHtml(body, `<div><img src="${chartDataUrl}" alt="LQ 图表" style="display:block;width:100%;border-radius:10px;border:1px solid #e5e7eb;background:#fff;" /></div>`);
                }
                this._appendExportHtml(body, this._buildExportTableHtml(['H3', 'POI', '密度', '熵', '可信度', '结构参考', '优势值'], rows));
                return panel;
            },
            async _buildH3GapPanelExportNode() {
                const summary = this.h3DerivedStats && this.h3DerivedStats.gapSummary;
                if (!summary) return null;
                const chartDataUrl = await this._renderExportChartDataUrl(this._buildH3GapChartExportOption(), 980, 580);
                const rows = (summary.rows || []).slice(0, Math.max(1, this.h3DecisionTopN)).map((row) => ([
                    this.shortH3Id(row.h3_id),
                    Math.round((row.demand_pct || 0) * 100),
                    Math.round((row.supply_pct || 0) * 100),
                    row.gap_score === null ? '-' : this._formatExportNumber(row.gap_score, 2),
                    (row.confidence && row.confidence.label) || '低',
                    row.gap_zone_label || '-',
                ]));
                const { panel, body } = this._createExportPanelHost('H3 评估 · 缺口评估');
                this._appendExportHtml(body, '<div class="h3-analysis-hint">先看“需求分位”和“供给分位”，再看两者差值；需求高且供给低的网格优先补位。</div>');
                if (summary.mappingWarning) {
                    this._appendExportHtml(body, `<div class="panel-placeholder" style="border-color:#fde68a;background:#fffbeb;color:#92400e;">${this._escapeExportHtml(summary.mappingWarning)}</div>`);
                }
                this._appendExportHtml(body, this._buildExportDecisionCardsHtml([
                    { label: '高缺口网格', value: summary.opportunityCount },
                    { label: '最高缺口分', value: this._formatExportNumber(summary.maxGap, 2) },
                    { label: '建议优先区', value: summary.recommendation || '-', small: true },
                ]));
                this._appendExportHtml(body, `<div class="panel-placeholder">${this._escapeExportHtml(summary.insight || '缺口分 = 需求百分位 - 目标业态供给百分位（越高越可能供给偏弱）')}</div>`);
                if (chartDataUrl) {
                    this._appendExportHtml(body, `<div><img src="${chartDataUrl}" alt="缺口散点图" style="display:block;width:100%;border-radius:10px;border:1px solid #e5e7eb;background:#fff;" /></div>`);
                }
                this._appendExportHtml(body, this._buildExportTableHtml(['H3', '需求分位', '供给分位', '缺口分', '可信度', '结论'], rows));
                return panel;
            },
            async _buildRoadMetricPanelExportNode(metric) {
                const summary = this.roadSyntaxSummary || null;
                if (!summary) return null;
                const legend = this.buildRoadSyntaxLegendModel(metric);
                const radiusOption = (this.roadSyntaxRadiusOptions() || []).find((item) => String(item.value || '') === String(this.roadSyntaxRadiusLabel || ''));
                const radiusLabel = radiusOption ? radiusOption.label : '等时圈内';
                const footnote = this.roadSyntaxFootnoteByMetric(metric);
                const switchText = this.roadSyntaxSwitchStatsText || '';
                const statusText = this.roadSyntaxStatus || '';
                const metricLabel = this.roadSyntaxLabelByMetric(metric);
                const sampleCount = this.roadSyntaxMetricDataCount(metric);
                const mainValue = this.formatRoadSyntaxMetricValue(metric);
                const chartDataUrl = metric === 'intelligibility'
                    ? await this._renderExportChartDataUrl(this._buildRoadSyntaxScatterChartExportOption(), 980, 580)
                    : null;
                const { panel, body } = this._createExportPanelHost(`路网分析 · ${metricLabel}`);
                this._appendExportHtml(body, this._buildExportCountBadgeGridHtml([
                    { label: '当前指标', value: metricLabel },
                    { label: '指标值', value: mainValue },
                    { label: '样本数', value: sampleCount },
                    { label: this.roadSyntaxMetricUsesRadius(metric) ? '半径' : '图模型', value: this.roadSyntaxMetricUsesRadius(metric) ? radiusLabel : this.roadSyntaxGraphModel },
                ], 2));
                this._appendExportHtml(body, this._buildExportLegendHtml(legend));
                if (footnote) {
                    this._appendExportHtml(body, `<div class="h3-analysis-hint">${this._escapeExportHtml(footnote)}</div>`);
                }
                if (switchText) {
                    this._appendExportHtml(body, `<div class="status-text">${this._escapeExportHtml(switchText)}</div>`);
                }
                if (statusText) {
                    this._appendExportHtml(body, `<div class="status-text">${this._escapeExportHtml(statusText)}</div>`);
                }
                if (metric === 'intelligibility' && chartDataUrl) {
                    const rv = this.roadSyntaxRegressionView();
                    this._appendExportHtml(body, this._buildExportDecisionCardsHtml([
                        { label: 'R', value: rv.r },
                        { label: 'R²', value: rv.r2 },
                        { label: '样本点数', value: rv.n },
                    ]));
                    this._appendExportHtml(body, `<div><img src="${chartDataUrl}" alt="可理解度散点图" style="display:block;width:100%;border-radius:10px;border:1px solid #e5e7eb;background:#fff;" /></div>`);
                }
                return panel;
            },
            async _captureFrontendPanelsForExport(selectedParts) {
                if (typeof html2canvas !== 'function') return [];
                const requestedParts = Array.from(new Set((selectedParts || []).filter((part) => this.isPanelExportPart(part))));
                if (!requestedParts.length) return [];
                if (requestedParts.some((part) => String(part || '').startsWith('h3_'))) {
                    this.computeH3DerivedStats();
                }
                const builders = {
                    poi_panel_png: () => this._buildPoiPanelExportNode(),
                    h3_metric_panel_png: () => this._buildH3MetricPanelExportNode(),
                    h3_structure_panel_png: () => this._buildH3StructurePanelExportNode(),
                    h3_typing_panel_png: () => this._buildH3TypingPanelExportNode(),
                    h3_lq_panel_png: () => this._buildH3LqPanelExportNode(),
                    h3_gap_panel_png: () => this._buildH3GapPanelExportNode(),
                    road_connectivity_panel_png: () => this._buildRoadMetricPanelExportNode('connectivity'),
                    road_control_panel_png: () => this._buildRoadMetricPanelExportNode('control'),
                    road_depth_panel_png: () => this._buildRoadMetricPanelExportNode('depth'),
                    road_choice_panel_png: () => this._buildRoadMetricPanelExportNode('choice'),
                    road_integration_panel_png: () => this._buildRoadMetricPanelExportNode('integration'),
                    road_intelligibility_panel_png: () => this._buildRoadMetricPanelExportNode('intelligibility'),
                };
                const panelIdByPart = {
                    poi_panel_png: 'poi_panel',
                    h3_metric_panel_png: 'h3_metric_panel',
                    h3_structure_panel_png: 'h3_structure_panel',
                    h3_typing_panel_png: 'h3_typing_panel',
                    h3_lq_panel_png: 'h3_lq_panel',
                    h3_gap_panel_png: 'h3_gap_panel',
                    road_connectivity_panel_png: 'road_connectivity_panel',
                    road_control_panel_png: 'road_control_panel',
                    road_depth_panel_png: 'road_depth_panel',
                    road_choice_panel_png: 'road_choice_panel',
                    road_integration_panel_png: 'road_integration_panel',
                    road_intelligibility_panel_png: 'road_intelligibility_panel',
                };
                const panels = [];
                for (const part of requestedParts) {
                    const builder = builders[part];
                    if (typeof builder !== 'function') continue;
                    const node = await builder();
                    if (!node) continue;
                    const pngBase64 = await this._captureExportPanelNode(node);
                    if (!pngBase64) continue;
                    panels.push({
                        panel_id: panelIdByPart[part],
                        png_base64: pngBase64,
                    });
                }
                return panels;
            },
            async _captureFrontendChartsForExport() {
                if (!window.echarts) return [];
                if (this.hasH3AnalysisForExport()) {
                    this.computeH3DerivedStats();
                }
                const chartDefs = [
                    {
                        chart_id: 'poi_category',
                        instance: this.poiChart,
                        canExport: this.hasPoisForExport(),
                        width: 980,
                        height: 520,
                        optionBuilder: () => this._buildPoiChartExportOption(),
                    },
                    {
                        chart_id: 'h3_category_distribution',
                        instance: this.h3CategoryChart,
                        canExport: this.hasH3AnalysisForExport(),
                        width: 980,
                        height: 520,
                        optionBuilder: () => this._buildH3CategoryChartExportOption(),
                    },
                    {
                        chart_id: 'h3_density_histogram',
                        instance: this.h3DensityChart,
                        canExport: this.hasH3AnalysisForExport(),
                        width: 980,
                        height: 560,
                        optionBuilder: () => this._buildH3DensityChartExportOption(),
                    },
                    {
                        chart_id: 'h3_structure_overview',
                        instance: this.h3StructureChart,
                        canExport: this.hasH3AnalysisForExport(),
                        width: 980,
                        height: 520,
                        optionBuilder: () => this._buildH3StructureChartExportOption(),
                    },
                    {
                        chart_id: 'h3_lq_distribution',
                        instance: this.h3LqChart,
                        canExport: this.hasH3AnalysisForExport(),
                        width: 980,
                        height: 520,
                        optionBuilder: () => this._buildH3LqChartExportOption(),
                    },
                    {
                        chart_id: 'h3_gap_scatter',
                        instance: this.h3GapChart,
                        canExport: this.hasH3AnalysisForExport(),
                        width: 980,
                        height: 580,
                        optionBuilder: () => this._buildH3GapChartExportOption(),
                    },
                    {
                        chart_id: 'road_intelligibility_scatter',
                        instance: this.roadSyntaxScatterChart,
                        canExport: this.hasRoadSyntaxSummaryForExport(),
                        width: 980,
                        height: 580,
                        optionBuilder: () => this._buildRoadSyntaxScatterChartExportOption(),
                    },
                ];
                const images = [];
                for (const def of chartDefs) {
                    if (!def || !def.canExport) continue;
                    let dataUrl = this._getChartDataUrl(def.instance, '#ffffff');
                    if (!dataUrl) {
                        const option = typeof def.optionBuilder === 'function' ? def.optionBuilder() : null;
                        if (!option) continue;
                        dataUrl = await this._renderExportChartDataUrl(option, def.width, def.height);
                    }
                    if (!dataUrl || typeof dataUrl !== 'string' || !dataUrl.startsWith('data:image/png;base64,')) {
                        continue;
                    }
                    images.push({
                        chart_id: def.chart_id,
                        png_base64: dataUrl,
                    });
                }
                return images;
            },
            _waitForUiPaint() {
                return new Promise((resolve) => {
                    window.requestAnimationFrame(() => resolve());
                });
            },
            _resolveH3ExportSourceFeatures() {
                if (this.hasH3AnalysisForExport()) {
                    return this.h3AnalysisGridFeatures;
                }
                if (this.hasH3GridForExport()) {
                    return Array.isArray(this.h3GridFeatures) ? this.h3GridFeatures : [];
                }
                return [];
            },
            _buildH3ExportGridFeatures() {
                const source = this._resolveH3ExportSourceFeatures();
                return (source || []).map((feature) => ({
                    type: String((feature && feature.type) || 'Feature'),
                    geometry: this._normalizeGeometryForExport((feature && feature.geometry) || null),
                    properties: Object.assign({}, (feature && feature.properties) || {}),
                })).filter((feature) => feature.geometry && feature.properties);
            },
            _normalizeCoordPointForExport(point) {
                if (Array.isArray(point) && point.length >= 2) {
                    const lng = Number(point[0]);
                    const lat = Number(point[1]);
                    if (Number.isFinite(lng) && Number.isFinite(lat)) return [lng, lat];
                }
                if (point && typeof point === 'object') {
                    const lng = Number(point.lng ?? point.lon);
                    const lat = Number(point.lat);
                    if (Number.isFinite(lng) && Number.isFinite(lat)) return [lng, lat];
                }
                return null;
            },
            _normalizeRingForExport(ring) {
                if (!Array.isArray(ring)) return [];
                const points = ring
                    .map((point) => this._normalizeCoordPointForExport(point))
                    .filter((point) => Array.isArray(point) && point.length >= 2);
                if (points.length < 3) return [];
                const first = points[0];
                const last = points[points.length - 1];
                if (first[0] !== last[0] || first[1] !== last[1]) {
                    points.push([first[0], first[1]]);
                }
                return points.length >= 4 ? points : [];
            },
            _normalizeGeometryForExport(geometry) {
                if (!geometry || typeof geometry !== 'object') return null;
                const type = String(geometry.type || '');
                const coords = geometry.coordinates;
                if (type === 'Polygon') {
                    if (!Array.isArray(coords)) return null;
                    const directRing = this._normalizeRingForExport(coords);
                    if (directRing.length) {
                        return { type: 'Polygon', coordinates: [directRing] };
                    }
                    const outerRing = this._normalizeRingForExport(coords[0]);
                    if (!outerRing.length) return null;
                    return { type: 'Polygon', coordinates: [outerRing] };
                }
                if (type === 'MultiPolygon') {
                    if (!Array.isArray(coords)) return null;
                    const polygons = [];
                    coords.forEach((polygon) => {
                        if (!Array.isArray(polygon)) return;
                        const directRing = this._normalizeRingForExport(polygon);
                        if (directRing.length) {
                            polygons.push([directRing]);
                            return;
                        }
                        const outerRing = this._normalizeRingForExport(polygon[0]);
                        if (outerRing.length) polygons.push([outerRing]);
                    });
                    if (!polygons.length) return null;
                    return { type: 'MultiPolygon', coordinates: polygons };
                }
                return null;
            },
            _normalizeIsochroneFeatureForExport() {
                const raw = this.lastIsochroneGeoJSON;
                if (!raw || typeof raw !== 'object') return null;

                let geometry = null;
                let properties = {};

                if (raw.type === 'Feature') {
                    geometry = this._normalizeGeometryForExport(raw.geometry || null);
                    properties = (raw.properties && typeof raw.properties === 'object') ? raw.properties : {};
                } else if (raw.geometry && typeof raw.geometry === 'object') {
                    geometry = this._normalizeGeometryForExport(raw.geometry);
                    properties = (raw.properties && typeof raw.properties === 'object') ? raw.properties : {};
                } else if (raw.type === 'Polygon' || raw.type === 'MultiPolygon') {
                    geometry = this._normalizeGeometryForExport(raw);
                }

                if (!geometry) return null;

                return {
                    type: 'Feature',
                    geometry: geometry,
                    properties: Object.assign({}, properties),
                };
            },
            _buildFrontendAnalysisForExport() {
                const result = {};
                try {
                    if (typeof this.getPoiCategoryChartStats === 'function') {
                        result.poi = {
                            category_stats: this.getPoiCategoryChartStats(),
                            poi_total: Array.isArray(this.allPoisDetails) ? this.allPoisDetails.length : 0,
                            active_tab: String(this.poiSubTab || ''),
                            analysis_tab: String(this.poiAnalysisSubTab || ''),
                        };
                    }
                    if (typeof this.computeH3DerivedStats === 'function') {
                        this.computeH3DerivedStats();
                    }
                    result.h3 = {
                        summary: this.h3AnalysisSummary || {},
                        derived_stats: this.h3DerivedStats || {},
                        metric_view: String(this.h3MetricView || ''),
                        structure_fill_mode: String(this.h3StructureFillMode || ''),
                        target_category: String(this.h3TargetCategory || ''),
                        target_category_label: (typeof this._getH3CategoryLabel === 'function')
                            ? String(this._getH3CategoryLabel(this.h3TargetCategory) || '')
                            : '',
                        top_n: Number(this.h3DecisionTopN || 0) || 0,
                    };
                    const regressionView = (typeof this.roadSyntaxRegressionView === 'function')
                        ? this.roadSyntaxRegressionView()
                        : {};
                    result.road = {
                        summary: this.roadSyntaxSummary || {},
                        metric: String(this.roadSyntaxMetric || ''),
                        main_tab: String(this.roadSyntaxMainTab || ''),
                        regression: regressionView || {},
                    };
                    result.population = {
                        summary_rows: (typeof this.getPopulationSummaryRows === 'function')
                            ? this.getPopulationSummaryRows()
                            : [],
                        analysis_view: String(this.populationAnalysisView || ''),
                        age_distribution: ((this.populationOverview && this.populationOverview.age_distribution) || []),
                        layer_summary: (this.populationLayer && this.populationLayer.summary) || {},
                    };
                    result.nightlight = {
                        summary_rows: (typeof this.getNightlightSummaryRows === 'function')
                            ? this.getNightlightSummaryRows()
                            : [],
                        analysis_view: String(this.nightlightAnalysisView || ''),
                        analysis: (this.nightlightLayer && this.nightlightLayer.analysis) || {},
                        legend_note: (typeof this.getNightlightLegendNote === 'function')
                            ? this.getNightlightLegendNote()
                            : '',
                    };
                    result.timeseries = {
                        active_tab: String(this.timeseriesActiveTab || ''),
                        summary_rows: (typeof this.getTimeseriesSummaryRows === 'function')
                            ? this.getTimeseriesSummaryRows()
                            : [],
                        insights: (typeof this.getTimeseriesInsights === 'function')
                            ? this.getTimeseriesInsights()
                            : [],
                        layer_summary: (this.timeseriesLayer && this.timeseriesLayer.summary) || {},
                    };
                } catch (err) {
                    console.warn('build frontend analysis payload failed', err);
                }
                return result;
            },
            _buildExportBundlePayload(selectedParts, mapSnapshotBase64, frontendPanels, frontendCharts) {
                const gridFeatures = this._buildH3ExportGridFeatures();
                const roadFeatures = Array.isArray(this.roadSyntaxRoadFeatures) ? this.roadSyntaxRoadFeatures : [];
                const pois = Array.isArray(this.allPoisDetails) ? this.allPoisDetails : [];
                const isochroneFeature = this._normalizeIsochroneFeatureForExport();
                const styleMode = (this.h3MainStage === 'analysis' && this.h3SubTab === 'structure_map')
                    ? (this.h3StructureFillMode === 'lisa_i' ? 'lisa_i' : 'gi_z')
                    : 'density';

                return {
                    template: 'business_common',
                    parts: selectedParts,
                    coord_type: 'gcj02',
                    context: {
                        center: this.selectedPoint ? [Number(this.selectedPoint.lng), Number(this.selectedPoint.lat)] : null,
                        time_min: Number(this.timeHorizon || 0) || null,
                        mode: this.transportMode || '',
                        source: this.resultDataSource || this.poiDataSource || '',
                        scope_source: this.scopeSource || '',
                        generated_at: new Date().toISOString(),
                    },
                    isochrone_feature: isochroneFeature,
                    pois: pois,
                    h3: {
                        grid_features: gridFeatures,
                        summary: this.h3AnalysisSummary || {},
                        charts: this.h3AnalysisCharts || {},
                        style_meta: {
                            style_mode: styleMode,
                            metric_view: this.h3MetricView,
                            structure_fill_mode: this.h3StructureFillMode,
                            legend: this.h3Legend || null,
                            gi_render_meta: (this.h3AnalysisSummary && this.h3AnalysisSummary.gi_render_meta) || null,
                            lisa_render_meta: (this.h3AnalysisSummary && this.h3AnalysisSummary.lisa_render_meta) || null,
                        },
                    },
                    road_syntax: {
                        roads: {
                            type: 'FeatureCollection',
                            features: roadFeatures,
                            count: roadFeatures.length,
                        },
                        summary: this.roadSyntaxSummary || {},
                        nodes: {
                            type: 'FeatureCollection',
                            features: Array.isArray(this.roadSyntaxNodes) ? this.roadSyntaxNodes : [],
                            count: Array.isArray(this.roadSyntaxNodes) ? this.roadSyntaxNodes.length : 0,
                        },
                        diagnostics: this.roadSyntaxDiagnostics || {},
                    },
                    frontend_charts: Array.isArray(frontendCharts) ? frontendCharts : [],
                    frontend_panels: Array.isArray(frontendPanels) ? frontendPanels : [],
                    frontend_analysis: this._buildFrontendAnalysisForExport(),
                    map_snapshot_png_base64: mapSnapshotBase64 || null,
                };
            },
            async exportAnalysisBundle() {
                if (this.isExportingBundle) {
                    this._showH3ExportToast('已有导出任务进行中，请稍候', 'info');
                    this.h3ExportTasksOpen = true;
                    return;
                }
                const selectedParts = this._normalizeExportBundleParts();
                const expandedParts = this._expandExportBundleParts(selectedParts);
                if (!expandedParts.length) {
                    this._showH3ExportToast('请至少勾选一个导出项', 'warning');
                    return;
                }

                this.isExportingBundle = true;
                const taskId = this._createExportBundleTask(selectedParts);
                this.h3ExportTasksOpen = true;
                try {
                    this._setExportBundleTaskProgress(taskId, 5, '准备导出环境');
                    await this.$nextTick();
                    await this._waitForUiPaint();

                    let mapSnapshotBase64 = null;
                    let frontendPanels = [];
                    let frontendCharts = [];
                    if (expandedParts.includes('map_snapshot_png')) {
                        this._setExportBundleTaskProgress(taskId, 12, '生成地图快照');
                        if (typeof html2canvas !== 'function') {
                            this._showH3ExportToast('截图组件未加载，地图快照将自动跳过', 'warning', 2600);
                        } else {
                            mapSnapshotBase64 = await this._captureMapSnapshotBase64();
                            if (!mapSnapshotBase64) {
                                this._showH3ExportToast('地图快照获取失败，将自动跳过该项', 'warning', 2600);
                            }
                        }
                    }
                    if (expandedParts.includes('frontend_charts_png')) {
                        this._setExportBundleTaskProgress(taskId, 20, '生成图表 PNG');
                        frontendCharts = await this._captureFrontendChartsForExport();
                        if (!frontendCharts.length) {
                            this._showH3ExportToast('当前没有可导出的图表 PNG，将自动跳过该项', 'warning', 2400);
                        }
                    }
                    if (expandedParts.some((part) => this.isPanelExportPart(part))) {
                        this._setExportBundleTaskProgress(taskId, 28, '生成结果子面板 PNG');
                        frontendPanels = await this._captureFrontendPanelsForExport(expandedParts);
                        if (!frontendPanels.length) {
                            this._showH3ExportToast('当前没有可导出的结果子面板，将自动跳过对应 PNG 项', 'warning', 2600);
                        }
                    }

                    this._setExportBundleTaskProgress(taskId, 50, '构建导出请求');
                    const payload = this._buildExportBundlePayload(expandedParts, mapSnapshotBase64, frontendPanels, frontendCharts);
                    await this._waitForUiPaint();
                    this._setExportBundleTaskProgress(taskId, 55, '上传导出请求');
                    const res = await this._postExportBundleWithProgress(payload, taskId);
                    this._setExportBundleTaskProgress(taskId, 99, '保存导出文件');
                    const blob = res.blob;
                    const filename = this._getFilenameFromContentDisposition(res.disposition)
                        || 'analysis_export.zip';
                    this._downloadBlobFile(blob, filename);
                    this._updateExportBundleTask(taskId, {
                        status: 'success',
                        status_label: '已完成',
                        filename: filename,
                        error: '',
                        progress_pct: 100,
                        progress_label: '导出完成',
                    });
                    this._showH3ExportToast(`导出成功：${filename}`, 'success');
                    this.h3ExportMenuOpen = false;
                } catch (e) {
                    console.error(e);
                    this._updateExportBundleTask(taskId, {
                        status: 'failed',
                        status_label: '失败',
                        error: String((e && e.message) || e || '未知错误'),
                        progress_label: '导出失败',
                    });
                    this._showH3ExportToast(`导出失败：${(e && e.message) || e}`, 'error', 3200);
                } finally {
                    this.isExportingBundle = false;
                }
            },
        };
    }

export { createAnalysisExportInitialState, createAnalysisExportMethods };
