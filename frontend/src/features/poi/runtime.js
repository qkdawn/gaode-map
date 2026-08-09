import { markRaw } from 'vue'
import { MarkerManager } from '../../map/markers'
import { FilterPanel } from '../../map/filters'
import { buildPoiRuntimePoints } from './records.js'

    function createAnalysisPoiRuntimeInitialState() {
        return {
            typeMapGroups: [],
            typeCodeToCategoryId: {},
            typePrefixToCategoryId: {},
            typeCodeToTypeId: {},
            typePrefixToTypeId: {},
            typeIdToGroupId: {},
            typeIdToLabel: {},
            categoryById: {},
            poiCategories: [],
            poiSubSelectionState: {},
            expandedPoiCategoryId: null,
            fetchSubtypeHitMap: {},
            fetchSubtypeProgress: {
                categoryId: '',
                categoryName: '',
                typeNamesPreview: [],
                typeNamesFullCount: 0,
                hiddenTypeCount: 0,
            },
            poiAutoFitViewEnabled: false,
            poiMapWriteGeneration: 0,
            poiManagerSerial: 0,
            poiActiveManagerId: 0,
            markerManager: null,
            filterPanel: null,
        };
    }

    function createAnalysisPoiRuntimeMethods() {
        return {
            normalizeTypeCode(value) {
                const digits = String(value || '').replace(/\D/g, '');
                return digits.length >= 6 ? digits.slice(0, 6) : digits;
            },
            _normalizeCategoryTitle(value) {
                return String(value || '').replace(/\s+/g, '').trim();
            },
            initializePoiCategoriesFromTypeMap() {
                const raw = (this.typeMapConfig && Array.isArray(this.typeMapConfig.groups))
                    ? this.typeMapConfig
                    : { groups: [] };
                this.typeCodeToCategoryId = {};
                this.typePrefixToCategoryId = {};
                this.typeCodeToTypeId = {};
                this.typePrefixToTypeId = {};
                this.typeIdToGroupId = {};
                this.typeIdToLabel = {};
                const groups = (raw.groups || []).map((group, gi) => {
                    const itemList = Array.isArray(group.items) ? group.items : [];
                    const mergedCodes = [];
                    const seenCodes = new Set();
                    let cardColor = '#888';
                    itemList.forEach((item) => {
                        if (!item || !item.id) return;
                        if (item.color && cardColor === '#888') {
                            cardColor = item.color;
                        }
                        String(item.types || '').split('|').forEach((rawCode) => {
                            const code = this.normalizeTypeCode(rawCode);
                            if (!code || seenCodes.has(code)) return;
                            seenCodes.add(code);
                            mergedCodes.push(code);
                            this.typeCodeToCategoryId[code] = String(group.id || '');
                            this.typeCodeToTypeId[code] = String(item.id || '');
                            if (code.length >= 2 && !this.typePrefixToCategoryId[code.slice(0, 2)]) {
                                this.typePrefixToCategoryId[code.slice(0, 2)] = String(group.id || '');
                            }
                            if (code.length >= 2 && !this.typePrefixToTypeId[code.slice(0, 2)]) {
                                this.typePrefixToTypeId[code.slice(0, 2)] = String(item.id || '');
                            }
                        });
                        this.typeIdToGroupId[String(item.id || '')] = String(group.id || '');
                        this.typeIdToLabel[String(item.id || '')] = String(item.label || item.id || '');
                    });

                    return {
                        id: String(group.id || `group-${gi}`),
                        name: String(group.title || group.id || `分类${gi + 1}`),
                        checked: true,
                        color: cardColor,
                        types: mergedCodes.join('|'),
                    };
                }).filter((group) => group.id && group.types);

                this.typeMapGroups = (raw.groups || []).map((group) => ({
                    ...group,
                    id: String(group.id || ''),
                    title: String(group.title || group.id || ''),
                    items: Array.isArray(group.items) ? group.items.map((item) => ({
                        ...item,
                        id: String(item.id || ''),
                        label: String(item.label || item.id || ''),
                    })) : []
                })).filter((group) => group.id);
                this.h3CategoryMeta = this._buildDefaultH3CategoryMeta();
                this.h3TargetCategory = this._resolveDefaultH3TargetCategory();

                this.poiCategories = groups;
                if (!this.poiCategories.length) {
                    this.poiCategories = [
                        { id: 'dining', name: '餐饮', checked: true, color: '#f44336', types: '050000' },
                        { id: 'shopping', name: '购物', checked: true, color: '#2196f3', types: '060000' },
                        { id: 'life', name: '生活', checked: true, color: '#ff9800', types: '070000' },
                        { id: 'transport', name: '交通', checked: true, color: '#4caf50', types: '150000' },
                        { id: 'scenic', name: '风景', checked: true, color: '#9c27b0', types: '110000' },
                        { id: 'education', name: '科教', checked: true, color: '#00bcd4', types: '140000' },
                        { id: 'medical', name: '医疗', checked: true, color: '#e91e63', types: '090000' },
                    ];
                    this.poiCategories.forEach((cat) => {
                        this.typeCodeToCategoryId[String(cat.types)] = cat.id;
                        this.typePrefixToCategoryId[String(cat.types).slice(0, 2)] = cat.id;
                        this.typeCodeToTypeId[String(cat.types)] = cat.id;
                        this.typePrefixToTypeId[String(cat.types).slice(0, 2)] = cat.id;
                        this.typeIdToGroupId[cat.id] = cat.id;
                        this.typeIdToLabel[cat.id] = cat.name;
                    });
                }
                this.categoryById = {};
                this.poiCategories.forEach((cat) => {
                    this.categoryById[cat.id] = cat;
                });
                this.syncH3PoiFilterSelection(true);
                this.poiSubSelectionState = {};
                this.typeMapGroups.forEach((group) => {
                    (group.items || []).forEach((item) => {
                        this.poiSubSelectionState[item.id] = true;
                    });
                });
                this.poiCategories.forEach((cat) => this.syncPoiCategorySelection(cat));
                this.expandedPoiCategoryId = null;
                this.resetFetchSubtypeProgress();
            },
            resetFetchSubtypeProgress() {
                this.fetchSubtypeHitMap = {};
                this.fetchSubtypeProgress = {
                    categoryId: '',
                    categoryName: '',
                    typeNamesPreview: [],
                    typeNamesFullCount: 0,
                    hiddenTypeCount: 0,
                };
            },
            getPoiTypeLabel(typeId) {
                const key = String(typeId || '');
                if (!key) return '';
                return this.typeIdToLabel[key] || key;
            },
            updateFetchSubtypeProgressDisplay(cat) {
                const categoryId = String((cat && cat.id) || '');
                if (!categoryId) return;
                const typeIds = Object.keys(this.fetchSubtypeHitMap[categoryId] || {});
                const typeNames = typeIds.map((typeId) => this.getPoiTypeLabel(typeId)).filter(Boolean);
                const previewLimit = 6;
                this.fetchSubtypeProgress = {
                    categoryId: categoryId,
                    categoryName: String((cat && cat.name) || categoryId),
                    typeNamesPreview: typeNames.slice(0, previewLimit),
                    typeNamesFullCount: typeNames.length,
                    hiddenTypeCount: Math.max(0, typeNames.length - previewLimit),
                };
            },
            accumulateFetchSubtypeHits(cat, poiList) {
                const categoryId = String((cat && cat.id) || '');
                if (!categoryId) return;
                if (!this.fetchSubtypeHitMap[categoryId]) {
                    this.fetchSubtypeHitMap[categoryId] = {};
                }
                const bucket = this.fetchSubtypeHitMap[categoryId];
                (poiList || []).forEach((poi) => {
                    const typeId = this.resolvePoiTypeId(poi && (poi.typecode || poi.type));
                    if (!typeId) return;
                    bucket[String(typeId)] = true;
                });
                this.updateFetchSubtypeProgressDisplay(cat);
            },
            getPoiSubItems(categoryId) {
                const group = (this.typeMapGroups || []).find((item) => String(item.id) === String(categoryId));
                return group && Array.isArray(group.items) ? group.items : [];
            },
            isPoiSubItemChecked(itemId) {
                return !!this.poiSubSelectionState[itemId];
            },
            getPoiSubSelectedCount(categoryId) {
                const items = this.getPoiSubItems(categoryId);
                if (!items.length) return 0;
                return items.filter((item) => !!this.poiSubSelectionState[item.id]).length;
            },
            togglePoiCategoryExpand(categoryId) {
                this.expandedPoiCategoryId = this.expandedPoiCategoryId === categoryId ? null : categoryId;
            },
            syncPoiCategorySelection(cat) {
                const items = this.getPoiSubItems(cat.id);
                if (!items.length) return;
                const selectedItems = items.filter((item) => !!this.poiSubSelectionState[item.id]);
                cat.checked = selectedItems.length > 0;
                const seen = new Set();
                const merged = [];
                selectedItems.forEach((item) => {
                    String(item.types || '').split('|').forEach((rawCode) => {
                        const code = this.normalizeTypeCode(rawCode);
                        if (!code || seen.has(code)) return;
                        seen.add(code);
                        merged.push(code);
                    });
                });
                cat.types = merged.join('|');
            },
            togglePoiCategory(cat, checked) {
                const items = this.getPoiSubItems(cat.id);
                if (!items.length) {
                    cat.checked = !!checked;
                    return;
                }
                items.forEach((item) => {
                    this.poiSubSelectionState[item.id] = !!checked;
                });
                this.syncPoiCategorySelection(cat);
            },
            onPoiSubItemToggle(cat, item, checked) {
                this.poiSubSelectionState[item.id] = !!checked;
                this.syncPoiCategorySelection(cat);
            },
            buildSelectedCategoryBuckets() {
                const buckets = [];
                (this.poiCategories || []).forEach((cat) => {
                    this.syncPoiCategorySelection(cat);
                    if (!cat.checked || !cat.types) return;
                    buckets.push({
                        id: cat.id,
                        name: cat.name,
                        types: String(cat.types || ''),
                    });
                });
                return buckets;
            },
            resolvePoiCategoryId(typeText) {
                const raw = String(typeText || '');
                if (raw && this.typeIdToGroupId[raw]) {
                    return this.typeIdToGroupId[raw];
                }
                const code = this.normalizeTypeCode(typeText);
                if (code && this.typeCodeToCategoryId[code]) {
                    return this.typeCodeToCategoryId[code];
                }
                if (code.length >= 2 && this.typePrefixToCategoryId[code.slice(0, 2)]) {
                    return this.typePrefixToCategoryId[code.slice(0, 2)];
                }
                return '';
            },
            resolvePoiTypeId(typeText) {
                const raw = String(typeText || '');
                if (raw && this.typeIdToGroupId[raw]) {
                    return raw;
                }
                const code = this.normalizeTypeCode(typeText);
                if (code && this.typeCodeToTypeId[code]) {
                    return this.typeCodeToTypeId[code];
                }
                if (code.length >= 2 && this.typePrefixToTypeId[code.slice(0, 2)]) {
                    return this.typePrefixToTypeId[code.slice(0, 2)];
                }
                return '';
            },
            resolvePoiCategory(typeText) {
                const id = this.resolvePoiCategoryId(typeText);
                return id ? this.categoryById[id] : null;
            },
            deduplicateFetchedPois(pois) {
                const list = Array.isArray(pois) ? pois : [];
                if (!list.length) return [];
                const seen = new Set();
                const out = [];
                for (const poi of list) {
                    if (!poi || typeof poi !== 'object') continue;
                    const id = poi.id ? String(poi.id) : '';
                    const name = poi.name ? String(poi.name).trim() : '';
                    const loc = Array.isArray(poi.location) ? poi.location : null;
                    const hasLoc = !!(loc && loc.length >= 2 && Number.isFinite(Number(loc[0])) && Number.isFinite(Number(loc[1])));
                    const key = id
                        ? `id:${id}`
                        : (hasLoc
                            ? `name_loc:${name}|${Number(loc[0]).toFixed(6)},${Number(loc[1]).toFixed(6)}`
                            : `name:${name}`);
                    if (seen.has(key)) continue;
                    seen.add(key);
                    out.push(poi);
                }
                return out;
            },
            bumpPoiMapWriteGeneration(_reason = '') {
                const next = Number(this.poiMapWriteGeneration || 0) + 1;
                this.poiMapWriteGeneration = next;
                return next;
            },
            enqueuePoiMapWrite(fn, options = {}) {
                if (typeof fn !== 'function') {
                    return {
                        accepted: false,
                        queued: false,
                        replaced: false,
                        id: 0,
                        size: 0,
                        promise: Promise.resolve({ ok: false, skipped: true, reason: 'invalid_fn' })
                    };
                }
                const opts = (options && typeof options === 'object') ? Object.assign({}, options) : {};
                const scopeRaw = (typeof opts.scope === 'string' && opts.scope.trim()) ? opts.scope.trim() : 'poi';
                const scope = /^[a-z0-9_-]+$/i.test(scopeRaw) ? scopeRaw : 'poi';
                const rawKey = (typeof opts.key === 'string' && opts.key) ? String(opts.key) : 'write';
                opts.key = rawKey.includes(':') ? rawKey : `${scope}:${rawKey}`;
                if (typeof opts.replaceExisting === 'undefined') {
                    opts.replaceExisting = true;
                }
                const usePoiGenerationGuard = scope === 'poi';
                const writeGeneration = usePoiGenerationGuard
                    ? Number(this.poiMapWriteGeneration || 0)
                    : -1;
                const userGuard = typeof opts.guard === 'function' ? opts.guard : null;
                opts.guard = (meta = {}) => {
                    if (usePoiGenerationGuard && Number(this.poiMapWriteGeneration || 0) !== writeGeneration) {
                        return false;
                    }
                    if (!userGuard) return true;
                    try {
                        return !!userGuard(meta);
                    } catch (_) {
                        return false;
                    }
                };
                opts.meta = Object.assign({}, (opts.meta && typeof opts.meta === 'object') ? opts.meta : {});
                if (usePoiGenerationGuard) {
                    opts.meta.poi_generation = writeGeneration;
                }
                if (typeof this.roadSyntaxEnqueueMapWrite === 'function') {
                    return this.roadSyntaxEnqueueMapWrite(fn, opts);
                }
                try {
                    if (usePoiGenerationGuard && typeof opts.guard === 'function' && !opts.guard(opts.meta || {})) {
                        return {
                            accepted: true,
                            queued: false,
                            replaced: false,
                            id: 0,
                            size: 0,
                            promise: Promise.resolve({
                                ok: false,
                                skipped: true,
                                reason: 'poi_generation_stale'
                            })
                        };
                    }
                    const value = fn((opts && opts.meta) || {});
                    const payload = (value && typeof value === 'object' && Object.prototype.hasOwnProperty.call(value, 'ok'))
                        ? Object.assign({}, value)
                        : { ok: value !== false, value };
                    return {
                        accepted: true,
                        queued: false,
                        replaced: false,
                        id: 0,
                        size: 0,
                        promise: Promise.resolve(payload)
                    };
                } catch (err) {
                    return {
                        accepted: true,
                        queued: false,
                        replaced: false,
                        id: 0,
                        size: 0,
                        promise: Promise.resolve({
                            ok: false,
                            reason: 'fallback_execute_error',
                            error: err && err.message ? err.message : String(err)
                        })
                    };
                }
            },
            safeMapSet(overlay, targetMap = null) {
                if (!overlay || typeof overlay.setMap !== 'function') return false;
                try {
                    overlay.setMap(targetMap || null);
                    return true;
                } catch (_) {
                    try { overlay.setMap(null); } catch (__){ }
                    return false;
                }
            },
            clearPoiOverlayLayers(options = {}) {
                const opts = (options && typeof options === 'object') ? options : {};
                const reason = (typeof opts.reason === 'string' && opts.reason) ? opts.reason : 'clear';
                const generation = this.bumpPoiMapWriteGeneration(`clear:${reason}`);
                const clearManager = opts.clearManager !== false;
                const clearSimpleMarkers = opts.clearSimpleMarkers !== false;
                const clearCenterMarker = !!opts.clearCenterMarker;
                const resetFilterPanel = opts.resetFilterPanel !== false;
                const immediate = Object.prototype.hasOwnProperty.call(opts, 'immediate') ? !!opts.immediate : true;
                const manager = clearManager ? this.markerManager : null;
                const managerMarkers = (manager && Array.isArray(manager.markers)) ? manager.markers.slice() : [];
                const simpleMarkers = clearSimpleMarkers && Array.isArray(this.poiMarkers) ? this.poiMarkers.slice() : [];
                const centerMarker = clearCenterMarker ? this.marker : null;

                if (clearManager) {
                    if (manager && typeof manager.dispose === 'function') {
                        try { manager.dispose(); } catch (_) { }
                    }
                    this.markerManager = null;
                    this.poiActiveManagerId = 0;
                    this.filterPanel = null;
                    if (resetFilterPanel) {
                        const filtersContainer = document.getElementById('filtersContainer');
                        if (filtersContainer) filtersContainer.innerHTML = '';
                    }
                }
                if (clearSimpleMarkers) {
                    this.poiMarkers = [];
                }
                if (clearCenterMarker) {
                    this.marker = null;
                }

                const clearTask = () => {
                    if (manager) {
                        if (typeof manager._destroyClusterersNow === 'function') {
                            manager._destroyClusterersNow();
                        } else if (typeof manager.destroyClusterers === 'function') {
                            manager.destroyClusterers({ immediate: true });
                        }
                    }
                    managerMarkers.forEach((marker) => {
                        if (!marker) return;
                        this.safeMapSet(marker, null);
                        if (typeof marker.setLabel === 'function') {
                            try { marker.setLabel(null); } catch (_) { }
                        }
                    });
                    simpleMarkers.forEach((marker) => {
                        if (!marker) return;
                        this.safeMapSet(marker, null);
                        if (typeof marker.setLabel === 'function') {
                            try { marker.setLabel(null); } catch (_) { }
                        }
                    });
                    if (centerMarker) {
                        this.safeMapSet(centerMarker, null);
                    }
                    if (manager) {
                        manager.markers = [];
                        manager.markersByType = {};
                        manager.markersByPid = {};
                        manager.typeClusterers = {};
                        manager.lastFilteredPoints = [];
                        manager.lastVisibleMarkerPids = new Set();
                    }
                    return {
                        ok: true,
                        poi_generation: generation,
                        manager_cleared: !!manager,
                        manager_markers_cleared: managerMarkers.length,
                        simple_markers_cleared: simpleMarkers.length,
                        center_marker_cleared: !!centerMarker
                    };
                };

                if (immediate) {
                    try {
                        return Promise.resolve(clearTask());
                    } catch (err) {
                        return Promise.resolve({
                            ok: false,
                            reason: 'clear_layers_immediate_failed',
                            error: err && err.message ? err.message : String(err)
                        });
                    }
                }

                const handle = this.enqueuePoiMapWrite(clearTask, {
                    key: `clear_layers:${reason}`,
                    replaceExisting: false,
                    meta: {
                        reason: `poi_clear_layers:${reason}`,
                        manager_markers: managerMarkers.length,
                        simple_markers: simpleMarkers.length,
                        clear_center_marker: !!centerMarker
                    }
                });
                return Promise.resolve(handle && handle.promise).catch(() => ({
                    ok: false,
                    reason: 'clear_layers_failed'
                }));
            },
            rebuildPoiRuntimeSystem(pois) {
                this.clearPoiOverlayLayers({
                    reason: 'update_poi_runtime_rebuild',
                    clearManager: true,
                    clearSimpleMarkers: true,
                    resetFilterPanel: true
                });

                const defaultTypeId = (() => {
                    for (const group of (this.typeMapGroups || [])) {
                        const firstItem = (group.items || [])[0];
                        if (firstItem && firstItem.id) return firstItem.id;
                    }
                    return (this.poiCategories[0] && this.poiCategories[0].id) ? this.poiCategories[0].id : 'default';
                })();
                const runtimePointResult = buildPoiRuntimePoints(pois, {
                    defaultTypeId,
                    normalizeLngLat: this.normalizeLngLat.bind(this),
                    resolveTypeId: this.resolvePoiTypeId.bind(this),
                    summarizeCoordInput: this.roadSyntaxSummarizeCoordInput.bind(this),
                });
                const { points, invalidPointCount, invalidPointSamples } = runtimePointResult;
                if (invalidPointCount > 0) {
                    console.warn('[poi-runtime] skipped invalid coordinates', {
                        invalid_count: invalidPointCount,
                        total_candidates: Array.isArray(pois) ? pois.length : 0,
                        samples: invalidPointSamples
                    });
                }

                const mapTypeConfig = {
                    groups: (this.typeMapGroups || []).map((group, index) => ({
                        id: String(group.id || `group-${index + 1}`),
                        title: String(group.title || group.id || `分类${index + 1}`),
                        toggleId: String(group.toggleId || `toggle-group-${index + 1}`),
                        filtersId: String(group.filtersId || `filters-group-${index + 1}`),
                        items: (group.items || []).map((item) => ({
                            id: String(item.id || ''),
                            label: String(item.label || item.id || ''),
                            color: item.color || '#888',
                            defaultChecked: this.poiSubSelectionState[item.id] !== false
                        })).filter((item) => item.id)
                    })).filter((group) => group.id && group.items.length > 0)
                };
                if (!mapTypeConfig.groups.length) {
                    mapTypeConfig.groups = [{
                        id: 'poi_group',
                        title: 'POI 分类',
                        toggleId: 'toggle_poi_group',
                        filtersId: 'filters-poi-group',
                        items: this.poiCategories.map((cat) => ({
                            id: String(cat.id || ''),
                            label: String(cat.name || cat.id || ''),
                            color: cat.color || '#888',
                            defaultChecked: cat.checked !== false
                        })).filter((item) => item.id)
                    }];
                }

                const centerObj = this.selectedPoint ? {
                    lng: this.selectedPoint.lng,
                    lat: this.selectedPoint.lat,
                    name: '中心点',
                    type: 'center'
                } : null;

                const managerGeneration = Number(this.poiMapWriteGeneration || 0);
                const managerId = Number(this.poiManagerSerial || 0) + 1;
                this.poiManagerSerial = managerId;
                let managerRef = null;
                const isWriteAllowed = () => {
                    return !!managerRef
                        && this.markerManager === managerRef
                        && Number(this.poiMapWriteGeneration || 0) === managerGeneration;
                };
                managerRef = markRaw(new MarkerManager(this.mapCore, {
                    mapData: { points: points, center: centerObj },
                    mapTypeConfig: mapTypeConfig,
                    enqueueMapWrite: this.enqueuePoiMapWrite.bind(this),
                    isWriteAllowed: isWriteAllowed,
                    interactionRawMarkerThreshold: 900,
                    interactionResumeDelayMs: 120
                }));
                this.markerManager = managerRef;
                this.poiActiveManagerId = managerId;
                this.markerManager.init();
                this.markerManager.renderMarkers();

                this.filterPanel = markRaw(new FilterPanel(this.markerManager, {
                    mapData: { points: points },
                    mapTypeConfig: mapTypeConfig,
                    flatMode: false,
                    autoFitView: !!this.poiAutoFitViewEnabled
                }));
                this.filterPanel.onFiltersChange = () => {
                    this.updatePoiCharts();
                };
                this.filterPanel.init();
                this.applySimplifyPointVisibility();
                this.updatePoiCharts();
            },
        };
    }

export { createAnalysisPoiRuntimeInitialState, createAnalysisPoiRuntimeMethods };
