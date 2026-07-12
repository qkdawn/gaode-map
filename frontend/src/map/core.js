import { MapUtils } from './utils'

    function MapCore(containerId, config) {
        this.containerId = containerId;
        this.config = config || {};
        this.center = this.config.center || (this.config.mapData && this.config.mapData.center) || { lng: 0, lat: 0 };
        this.zoom = this.config.zoom || 13;
        this.zooms = this.config.zooms || [3, 20];
        this.mapData = this.config.mapData || {};
        this.mapMode = (new URLSearchParams(window.location.search).get('type') || 'around').toLowerCase();
        this.currentRadius = typeof this.mapData.radius === 'number'
            ? this.mapData.radius
            : (typeof this.config.radius === 'number' ? this.config.radius : null);
        this.gridWebglPreferred = this.config.gridWebglEnabled !== false;
        this.basemapSource = ['amap', 'osm', 'tianditu'].indexOf(this.config.basemapSource) >= 0
            ? this.config.basemapSource
            : 'amap';
        this.basemapMuted = !!this.config.basemapMuted;
        this.tiandituKey = (this.config.tiandituKey || '').trim();
        this.tiandituContainerId = this.config.tiandituContainerId || '';
        this._defaultZooms = Array.isArray(this.zooms) && this.zooms.length >= 2
            ? [this.zooms[0], this.zooms[1]]
            : [3, 20];
        this._tiandituZooms = [
            Math.max(1, this._defaultZooms[0]),
            Math.min(18, this._defaultZooms[1])
        ];
        if (this._tiandituZooms[0] > this._tiandituZooms[1]) {
            this._tiandituZooms = [3, 18];
        }

        this.map = null;
        this.mainCircle = null;
        this.cityCircles = [];
        this.cityCircleMap = {};
        this.boundaryPolygons = [];
        this.customPolygons = [];
        this.gridPolygons = [];
        this.gridPolygonMap = {};
        this.gridFeatureMap = {};
        this.gridFeatureList = [];
        this.focusedSpatialOverlays = [];
        this.spatialPresentationOverlays = [];
        this.gridStructureBoundaryOverlays = [];
        this.gridStructureSymbolOverlays = [];
        this.focusedGridPolygon = null;
        this.focusedGridOverlay = null;
        this._gridFocusAnimTimer = null;
        this._gridFocusViewBeforeLock = null;
        this.gridWebglEnabled = false;
        this._gridLocaLoaderPromise = null;
        this.gridLocaContainer = null;
        this.gridLocaFillLayer = null;
        this.gridLocaBorderLayer = null;

        this.clusterPluginReady = false;
        this.heatmapPluginReady = false;
        this._pluginPromise = null;
        this.poiHeatmap = null;
        this.poiHeatmapConfig = null;
        this.populationRasterLayer = null;
        this.populationRasterLayerMode = '';
        this.populationRasterBounds = null;
        this.populationRasterUrl = '';
        this.populationRasterOpacity = 0.58;
        this.populationRasterCanvas = null;
        this.populationRasterContext = null;
        this.populationRasterImage = null;
        this.populationRasterClipPolygon = [];
        this.populationPixelGridEnabled = false;
        this.populationPixelGridFocus = null;
        this.populationPixelGridWindowSize = 15;
        this.populationPixelGridZoomThreshold = 16;
        this.populationRasterRenderFrame = 0;
        this.populationRasterListeners = [];
        this._amapTileLayer = null;
        this._osmTileLayer = null;
        this._tdtVecLayer = null;
        this._tdtCvaLayer = null;
        this._blankTileLayer = null;
        this.tiandituMap = null;
        this.lastBasemapError = null;
        this.analysisBackdropMode = '';
    }

    MapCore.prototype.initMap = function () {
        var initialFeatures = ['bg', 'point', 'road', 'building'];
        this.map = new AMap.Map(this.containerId, {
            zoom: this.zoom,
            zooms: this.zooms,
            center: [this.center.lng, this.center.lat],
            features: initialFeatures
        });

        this.updateMainCircle(this.currentRadius);
        this.rebuildCityCircles(this.currentRadius);
        this.setBasemapSource(this.basemapSource);
        this.setBasemapMuted(this.basemapMuted);
        if (this.gridWebglPreferred) {
            this.ensureGridLocaReady();
        }

        if (this.mapMode === 'city') {
            var cityBoundaryId = this.mapData.adcode || (this.center && this.center.adcode) || (this.center && this.center.name);
            this.drawCityBoundary(cityBoundaryId);
        }
    };

    MapCore.prototype.loadPlugins = function () {
        var self = this;
        if (this._pluginPromise) return this._pluginPromise;

        this._pluginPromise = new Promise(function (resolve) {
            AMap.plugin(['AMap.MarkerClusterer', 'AMap.Heatmap'], function () {
                self.clusterPluginReady = true;
                self.heatmapPluginReady = true;
                resolve();
            });
        });

        return this._pluginPromise;
    };

    MapCore.prototype.clearPoiHeatmap = function () {
        if (!this.poiHeatmap) {
            this.poiHeatmapConfig = null;
            return;
        }
        try {
            if (typeof this.poiHeatmap.hide === 'function') {
                this.poiHeatmap.hide();
            }
        } catch (err) {
            console.warn('[MapCore] hide poi heatmap failed:', err);
        }
        try {
            if (typeof this.poiHeatmap.setDataSet === 'function') {
                this.poiHeatmap.setDataSet({ data: [], max: 1 });
            }
        } catch (err2) {
            console.warn('[MapCore] clear poi heatmap dataset failed:', err2);
        }
        try {
            if (typeof this.poiHeatmap.setMap === 'function') {
                this.poiHeatmap.setMap(null);
            }
        } catch (err3) {
            console.warn('[MapCore] detach poi heatmap failed:', err3);
        }
        this.poiHeatmap = null;
        this.poiHeatmapConfig = null;
    };

    MapCore.prototype.clearPopulationRasterOverlay = function () {
        if (this.populationRasterRenderFrame && typeof window !== 'undefined' && window.cancelAnimationFrame) {
            window.cancelAnimationFrame(this.populationRasterRenderFrame);
        }
        this.populationRasterRenderFrame = 0;
        this._detachPopulationRasterListeners();
        try {
            if (this.populationRasterLayer && typeof this.populationRasterLayer.setMap === 'function') {
                this.populationRasterLayer.setMap(null);
            }
        } catch (err) {
            console.warn('[MapCore] clear population raster failed:', err);
        }
        if (this.populationRasterCanvas && this.populationRasterCanvas.parentNode) {
            this.populationRasterCanvas.parentNode.removeChild(this.populationRasterCanvas);
        }
        this.populationRasterLayer = null;
        this.populationRasterLayerMode = '';
        this.populationRasterBounds = null;
        this.populationRasterUrl = '';
        this.populationRasterOpacity = 0.58;
        this.populationRasterCanvas = null;
        this.populationRasterContext = null;
        this.populationRasterImage = null;
        this.populationRasterClipPolygon = [];
        this.populationPixelGridEnabled = false;
        this.populationPixelGridFocus = null;
    };

    MapCore.prototype._detachPopulationRasterListeners = function () {
        if (!this.map || !this.populationRasterListeners.length || typeof this.map.off !== 'function') {
            this.populationRasterListeners = [];
            return;
        }
        this.populationRasterListeners.forEach(function (item) {
            try {
                this.map.off(item.event, item.handler);
            } catch (_) { }
        }, this);
        this.populationRasterListeners = [];
    };

    MapCore.prototype._attachPopulationRasterListeners = function () {
        if (!this.map || typeof this.map.on !== 'function' || this.populationRasterListeners.length) return;
        var self = this;
        ['mapmove', 'zoomchange', 'resize'].forEach(function (eventName) {
            var handler = function () {
                self._schedulePopulationRasterRender();
            };
            try {
                self.map.on(eventName, handler);
                self.populationRasterListeners.push({ event: eventName, handler: handler });
            } catch (_) { }
        });
    };

    MapCore.prototype._getMapContainerNode = function () {
        if (this.map && typeof this.map.getContainer === 'function') {
            return this.map.getContainer();
        }
        if (typeof document === 'undefined') return null;
        return document.getElementById(this.containerId);
    };

    MapCore.prototype._applyAnalysisBackdrop = function () {
        var container = this._getMapContainerNode();
        if (!container) return;
        if (!container.dataset.defaultBackgroundColor) {
            container.dataset.defaultBackgroundColor = container.style.backgroundColor || '';
        }
        if (!container.dataset.defaultBackgroundImage) {
            container.dataset.defaultBackgroundImage = container.style.backgroundImage || '';
        }

        if (this.analysisBackdropMode === 'nightlight') {
            container.style.backgroundColor = '#162033';
            container.style.backgroundImage = 'radial-gradient(circle at 52% 42%, rgba(251, 191, 36, 0.1) 0%, rgba(35, 49, 74, 0.82) 28%, rgba(22, 32, 51, 0.94) 62%, rgba(10, 15, 27, 1) 100%)';
            return;
        }

        container.style.backgroundColor = container.dataset.defaultBackgroundColor || '';
        container.style.backgroundImage = container.dataset.defaultBackgroundImage || '';
    };

    MapCore.prototype.setAnalysisBackdropMode = function (mode) {
        this.analysisBackdropMode = String(mode || '').trim().toLowerCase();
        this._applyAnalysisBackdrop();
    };

    MapCore.prototype._normalizePopulationClipPolygon = function (clipPolygon) {
        var rings = [];
        var appendRing = function (candidate) {
            var normalized = this._normalizePathPoints(candidate, 3);
            if (normalized.length < 3) return;
            var first = normalized[0];
            var last = normalized[normalized.length - 1];
            if (!last || first[0] !== last[0] || first[1] !== last[1]) {
                normalized = normalized.concat([[first[0], first[1]]]);
            }
            rings.push(normalized);
        }.bind(this);

        if (!Array.isArray(clipPolygon) || !clipPolygon.length) return rings;
        if (this._normalizeLngLatPoint(clipPolygon[0])) {
            appendRing(clipPolygon);
            return rings;
        }

        clipPolygon.forEach(function (item) {
            if (Array.isArray(item) && item.length && this._normalizeLngLatPoint(item[0])) {
                appendRing(item);
                return;
            }
            if (Array.isArray(item) && item.length && Array.isArray(item[0]) && item[0].length && this._normalizeLngLatPoint(item[0][0])) {
                appendRing(item[0]);
            }
        }, this);
        return rings;
    };

    MapCore.prototype._populationLngLatToPixel = function (pt) {
        var pair = this._normalizeLngLatPoint(pt);
        if (!pair || !this.map || typeof this.map.lngLatToContainer !== 'function' || !(window.AMap && AMap.LngLat)) {
            return null;
        }
        try {
            var pixel = this.map.lngLatToContainer(new AMap.LngLat(pair[0], pair[1]));
            if (!pixel) return null;
            var x = typeof pixel.getX === 'function' ? Number(pixel.getX()) : Number(pixel.x);
            var y = typeof pixel.getY === 'function' ? Number(pixel.getY()) : Number(pixel.y);
            if (!Number.isFinite(x) || !Number.isFinite(y)) return null;
            return [x, y];
        } catch (_) {
            return null;
        }
    };

    MapCore.prototype._syncPopulationRasterCanvas = function () {
        var container = this._getMapContainerNode();
        var canvas = this.populationRasterCanvas;
        if (!container || !canvas) return null;
        var width = Math.max(1, Math.round(container.clientWidth || container.offsetWidth || 0));
        var height = Math.max(1, Math.round(container.clientHeight || container.offsetHeight || 0));
        var dpr = (typeof window !== 'undefined' && window.devicePixelRatio) ? Math.max(1, window.devicePixelRatio) : 1;
        var targetWidth = Math.max(1, Math.round(width * dpr));
        var targetHeight = Math.max(1, Math.round(height * dpr));
        if (canvas.width !== targetWidth) canvas.width = targetWidth;
        if (canvas.height !== targetHeight) canvas.height = targetHeight;
        canvas.style.width = width + 'px';
        canvas.style.height = height + 'px';
        return { width: width, height: height, dpr: dpr };
    };

    MapCore.prototype._drawPopulationPixelGrid = function (ctx, left, top, width, height) {
        if (
            !this.populationPixelGridEnabled
            || !this.populationPixelGridFocus
            || !this.populationRasterImage
            || !this.map
        ) {
            return;
        }

        var zoom = typeof this.map.getZoom === 'function' ? Number(this.map.getZoom()) : 0;
        if (!(zoom >= this.populationPixelGridZoomThreshold)) return;

        var focusLngLat = this._normalizeLngLatPoint(this.populationPixelGridFocus);
        var focusPixel = this._populationLngLatToPixel(focusLngLat);
        if (!focusPixel) return;

        var right = left + width;
        var bottom = top + height;
        if (focusPixel[0] < left || focusPixel[0] > right || focusPixel[1] < top || focusPixel[1] > bottom) {
            return;
        }

        var imageWidth = Math.max(1, Math.round(Number(this.populationRasterImage.naturalWidth || this.populationRasterImage.width || 0)));
        var imageHeight = Math.max(1, Math.round(Number(this.populationRasterImage.naturalHeight || this.populationRasterImage.height || 0)));
        if (!(imageWidth > 0 && imageHeight > 0)) return;

        var relativeX = (focusPixel[0] - left) / width;
        var relativeY = (focusPixel[1] - top) / height;
        if (!Number.isFinite(relativeX) || !Number.isFinite(relativeY)) return;

        var focusCol = Math.max(0, Math.min(imageWidth - 1, Math.floor(relativeX * imageWidth)));
        var focusRow = Math.max(0, Math.min(imageHeight - 1, Math.floor(relativeY * imageHeight)));
        var windowSize = Math.max(3, Math.round(Number(this.populationPixelGridWindowSize) || 15));
        if (windowSize % 2 === 0) windowSize += 1;
        var halfWindow = Math.floor(windowSize / 2);
        var startCol = Math.max(0, focusCol - halfWindow);
        var endCol = Math.min(imageWidth - 1, focusCol + halfWindow);
        var startRow = Math.max(0, focusRow - halfWindow);
        var endRow = Math.min(imageHeight - 1, focusRow + halfWindow);

        var projectX = function (colIndex) {
            return left + (colIndex / imageWidth) * width;
        };
        var projectY = function (rowIndex) {
            return top + (rowIndex / imageHeight) * height;
        };
        var crisp = function (value) {
            return Math.round(value) + 0.5;
        };

        ctx.save();
        ctx.beginPath();
        for (var col = startCol; col <= endCol + 1; col += 1) {
            var x = crisp(projectX(col));
            ctx.moveTo(x, projectY(startRow));
            ctx.lineTo(x, projectY(endRow + 1));
        }
        for (var row = startRow; row <= endRow + 1; row += 1) {
            var y = crisp(projectY(row));
            ctx.moveTo(projectX(startCol), y);
            ctx.lineTo(projectX(endCol + 1), y);
        }
        ctx.lineWidth = 1;
        ctx.strokeStyle = 'rgba(255,255,255,0.34)';
        ctx.stroke();

        var cellLeft = projectX(focusCol);
        var cellTop = projectY(focusRow);
        var cellWidth = Math.max(1, projectX(focusCol + 1) - cellLeft);
        var cellHeight = Math.max(1, projectY(focusRow + 1) - cellTop);
        ctx.fillStyle = 'rgba(255,255,255,0.10)';
        ctx.fillRect(cellLeft, cellTop, cellWidth, cellHeight);
        ctx.lineWidth = 1.4;
        ctx.strokeStyle = 'rgba(15,23,42,0.78)';
        ctx.strokeRect(
            crisp(cellLeft),
            crisp(cellTop),
            Math.max(0, Math.round(cellWidth) - 1),
            Math.max(0, Math.round(cellHeight) - 1)
        );
        ctx.restore();
    };

    MapCore.prototype._renderPopulationRasterOverlay = function () {
        this.populationRasterRenderFrame = 0;
        if (!this.populationRasterCanvas || !this.populationRasterContext) return;
        var canvasState = this._syncPopulationRasterCanvas();
        if (!canvasState) return;

        var ctx = this.populationRasterContext;
        ctx.setTransform(canvasState.dpr, 0, 0, canvasState.dpr, 0, 0);
        ctx.clearRect(0, 0, canvasState.width, canvasState.height);

        if (!this.populationRasterImage || !this.populationRasterBounds || this.populationRasterBounds.length < 2) {
            return;
        }

        var sw = this.populationRasterBounds[0];
        var ne = this.populationRasterBounds[1];
        var nwPixel = this._populationLngLatToPixel([sw[0], ne[1]]);
        var sePixel = this._populationLngLatToPixel([ne[0], sw[1]]);
        if (!nwPixel || !sePixel) return;

        var left = Math.min(nwPixel[0], sePixel[0]);
        var top = Math.min(nwPixel[1], sePixel[1]);
        var width = Math.abs(sePixel[0] - nwPixel[0]);
        var height = Math.abs(sePixel[1] - nwPixel[1]);
        if (!(width > 0 && height > 0)) return;

        if (this.populationRasterClipPolygon.length) {
            ctx.save();
            ctx.beginPath();
            this.populationRasterClipPolygon.forEach(function (ring) {
                var started = false;
                (Array.isArray(ring) ? ring : []).forEach(function (pt) {
                    var px = this._populationLngLatToPixel(pt);
                    if (!px) return;
                    if (!started) {
                        ctx.moveTo(px[0], px[1]);
                        started = true;
                    } else {
                        ctx.lineTo(px[0], px[1]);
                    }
                }, this);
                if (started) ctx.closePath();
            }, this);
            try {
                ctx.clip('evenodd');
            } catch (_) {
                ctx.clip();
            }
        }

        ctx.globalAlpha = Math.max(0.05, Math.min(1, Number(this.populationRasterOpacity) || 0.58));
        ctx.imageSmoothingEnabled = false;
        ctx.mozImageSmoothingEnabled = false;
        ctx.webkitImageSmoothingEnabled = false;
        ctx.msImageSmoothingEnabled = false;
        ctx.drawImage(this.populationRasterImage, left, top, width, height);
        ctx.globalAlpha = 1;
        this._drawPopulationPixelGrid(ctx, left, top, width, height);

        if (this.populationRasterClipPolygon.length) {
            ctx.restore();
        }
    };

    MapCore.prototype._schedulePopulationRasterRender = function () {
        if (this.populationRasterRenderFrame || typeof window === 'undefined' || !window.requestAnimationFrame) {
            if (!this.populationRasterRenderFrame) {
                this._renderPopulationRasterOverlay();
            }
            return;
        }
        var self = this;
        this.populationRasterRenderFrame = window.requestAnimationFrame(function () {
            self._renderPopulationRasterOverlay();
        });
    };

    MapCore.prototype._ensurePopulationRasterLayer = function () {
        if (this.populationRasterCanvas && this.populationRasterContext) return true;
        if (typeof document === 'undefined') return false;

        var canvas = document.createElement('canvas');
        canvas.setAttribute('data-population-raster-canvas', '1');
        canvas.style.pointerEvents = 'none';
        canvas.style.position = 'absolute';
        canvas.style.inset = '0';
        canvas.style.zIndex = '104';

        var context = canvas.getContext('2d');
        if (!context) return false;

        this.populationRasterCanvas = canvas;
        this.populationRasterContext = context;
        var container = this._getMapContainerNode();
        if (!container) return false;
        if (typeof window !== 'undefined' && window.getComputedStyle && window.getComputedStyle(container).position === 'static') {
            container.style.position = 'relative';
        }
        // Keep the raster overlay fully in screen space. AMap.CustomLayer applies
        // additional internal transforms during pan/zoom, which makes our local
        // pixel-grid diagnostics drift away from the raster image.
        container.appendChild(canvas);
        this.populationRasterLayer = {
            setMap: function (mapInstance) {
                if (!mapInstance && canvas.parentNode) {
                    canvas.parentNode.removeChild(canvas);
                }
            }
        };
        this.populationRasterLayerMode = 'dom';
        this._attachPopulationRasterListeners();
        return true;
    };

    MapCore.prototype.setPopulationRasterOverlay = function (options) {
        if (!this.map) {
            return { ok: false, reason: 'population_raster_layer_unavailable' };
        }
        var safe = options && typeof options === 'object' ? options : {};
        var imageUrl = String(safe.imageUrl || '').trim();
        var bounds = Array.isArray(safe.bounds) ? safe.bounds : [];
        if (!imageUrl || bounds.length < 2) {
            this.clearPopulationRasterOverlay();
            return { ok: false, reason: 'population_raster_payload_invalid' };
        }
        var sw = this._normalizeLngLatPoint(bounds[0]);
        var ne = this._normalizeLngLatPoint(bounds[1]);
        if (!sw || !ne) {
            this.clearPopulationRasterOverlay();
            return { ok: false, reason: 'population_raster_bounds_invalid' };
        }
        var opacity = Math.max(0.05, Math.min(1, Number(safe.opacity) || 0.58));
        var clipPolygon = this._normalizePopulationClipPolygon(safe.clipPolygon);
        var pixelGridEnabled = !!safe.pixelGridEnabled;
        var pixelGridFocus = this._normalizeLngLatPoint(safe.pixelGridFocus);

        if (!this.populationRasterLayer && !this._ensurePopulationRasterLayer()) {
            this.clearPopulationRasterOverlay();
            return { ok: false, reason: 'population_raster_layer_unavailable' };
        }

        this.populationRasterBounds = [sw, ne];
        this.populationRasterOpacity = opacity;
        this.populationRasterClipPolygon = clipPolygon;
        this.populationPixelGridEnabled = pixelGridEnabled;
        this.populationPixelGridFocus = pixelGridFocus;

        var shouldReloadImage = this.populationRasterUrl !== imageUrl || !this.populationRasterImage;
        this.populationRasterUrl = imageUrl;
        if (shouldReloadImage) {
            var self = this;
            var image = new Image();
            image.crossOrigin = 'anonymous';
            image.onload = function () {
                if (self.populationRasterUrl !== imageUrl) return;
                self.populationRasterImage = image;
                self._schedulePopulationRasterRender();
            };
            image.onerror = function (err) {
                console.warn('[MapCore] population raster image load failed:', err);
            };
            image.src = imageUrl;
            this.populationRasterImage = image.complete ? image : null;
        }
        this._schedulePopulationRasterRender();
        return { ok: true };
    };

    MapCore.prototype.renderPoiHeatmap = function (points, options) {
        var self = this;
        if (!this.map) {
            return Promise.resolve({ ok: false, reason: 'map_unavailable' });
        }

        var normalizedPoints = (Array.isArray(points) ? points : []).map(function (item) {
            var pair = self._normalizeLngLatPoint(item);
            if (!pair) return null;
            var count = Number(item && item.count);
            return {
                lng: pair[0],
                lat: pair[1],
                count: Number.isFinite(count) && count > 0 ? count : 1
            };
        }).filter(function (item) { return !!item; });

        if (!normalizedPoints.length) {
            this.clearPoiHeatmap();
            return Promise.resolve({ ok: true, reason: 'no_points', count: 0 });
        }

        var safeOptions = options && typeof options === 'object' ? options : {};
        var radius = Math.max(8, Math.min(80, Number(safeOptions.radius) || 28));
        var max = Math.max(1, Number(safeOptions.max) || Math.max(8, Math.ceil(normalizedPoints.length / 30)));
        var opacity = Math.max(0.05, Math.min(1, Number(safeOptions.opacity) || 0.7));
        var gradient = safeOptions.gradient && typeof safeOptions.gradient === 'object'
            ? safeOptions.gradient
            : {
                0.2: '#60a5fa',
                0.4: '#22c55e',
                0.65: '#f59e0b',
                0.9: '#ef4444'
            };
        var nextConfig = {
            radius: radius,
            max: max,
            opacity: opacity,
            gradient: gradient
        };
        var prevConfig = this.poiHeatmapConfig ? JSON.stringify(this.poiHeatmapConfig) : '';
        var currentConfig = JSON.stringify(nextConfig);

        return this.loadPlugins().then(function () {
            if (!window.AMap || typeof AMap.Heatmap !== 'function') {
                return { ok: false, reason: 'heatmap_plugin_unavailable' };
            }

            if (!self.poiHeatmap || prevConfig !== currentConfig) {
                self.clearPoiHeatmap();
                self.poiHeatmap = new AMap.Heatmap(self.map, {
                    radius: radius,
                    opacity: [0, opacity],
                    gradient: gradient,
                    zooms: [3, 20]
                });
                self.poiHeatmapConfig = nextConfig;
            } else if (typeof self.poiHeatmap.setOptions === 'function') {
                try {
                    self.poiHeatmap.setOptions({
                        radius: radius,
                        opacity: [0, opacity],
                        gradient: gradient,
                        zooms: [3, 20]
                    });
                    self.poiHeatmapConfig = nextConfig;
                } catch (err) {
                    console.warn('[MapCore] update poi heatmap options failed, recreating:', err);
                    self.clearPoiHeatmap();
                    self.poiHeatmap = new AMap.Heatmap(self.map, {
                        radius: radius,
                        opacity: [0, opacity],
                        gradient: gradient,
                        zooms: [3, 20]
                    });
                    self.poiHeatmapConfig = nextConfig;
                }
            }

            self.poiHeatmap.setDataSet({
                data: normalizedPoints,
                max: max
            });
            if (typeof self.poiHeatmap.show === 'function') {
                self.poiHeatmap.show();
            }
            return { ok: true, count: normalizedPoints.length };
        }).catch(function (err) {
            console.error('[MapCore] render poi heatmap failed:', err);
            return {
                ok: false,
                reason: 'render_poi_heatmap_failed',
                error: err && err.message ? err.message : String(err)
            };
        });
    };

    MapCore.prototype.setRadius = function (radius) {
        this.currentRadius = radius;
        this.updateMainCircle(radius);
        this.rebuildCityCircles(radius);
    };

    MapCore.prototype.updateMainCircle = function (radius) {
        if (this.mainCircle) {
            this.mainCircle.setMap(null);
        }
        if (!radius) {
            this.mainCircle = null;
            return;
        }
        this.mainCircle = new AMap.Circle({
            center: [this.center.lng, this.center.lat],
            radius: radius,
            strokeColor: "#FF0000",
            strokeWeight: 3,
            fillColor: "#FF0000",
            fillOpacity: 0
        });
        this.map.add(this.mainCircle);
    };

    MapCore.prototype.rebuildCityCircles = function (radius) {
        var self = this;
        Object.keys(this.cityCircleMap).forEach(function (pid) {
            var circle = self.cityCircleMap[pid];
            if (!circle) return;
            circle.setMap(null);
            if (radius) {
                circle.setRadius(radius);
            }
        });
        this.cityCircles = [];
        if (this.mapMode !== 'city' || !radius) return;

        (this.mapData.points || []).forEach(function (point, idx) {
            var pid = point._pid || ('city-' + idx);
            point._pid = pid;
            var circle = self.cityCircleMap[pid];
            if (!circle) {
                circle = new AMap.Circle({
                    center: [point.lng, point.lat],
                    radius: radius,
                    strokeColor: "#009688",
                    strokeWeight: 2,
                    fillColor: "#009688",
                    fillOpacity: 0
                });
                self.cityCircleMap[pid] = circle;
            } else {
                circle.setRadius(radius);
            }
            self.cityCircles.push(circle);
        });
    };

    MapCore.prototype.updateCityCirclesVisibility = function (visiblePidSet) {
        var self = this;
        if (this.mapMode !== 'city') return;
        if (!this.currentRadius) {
            Object.keys(this.cityCircleMap).forEach(function (pid) {
                var circle = self.cityCircleMap[pid];
                if (circle) {
                    circle.setMap(null);
                }
            });
            this.cityCircles = [];
            return;
        }
        this.cityCircles = [];
        Object.keys(this.cityCircleMap).forEach(function (pid) {
            var circle = self.cityCircleMap[pid];
            if (!circle) return;
            if (visiblePidSet && visiblePidSet.has(pid)) {
                circle.setMap(self.map);
                self.cityCircles.push(circle);
            } else {
                circle.setMap(null);
            }
        });
    };

    MapCore.prototype.clearBoundaryPolygons = function () {
        this.boundaryPolygons.forEach(function (polygon) { polygon.setMap(null); });
        this.boundaryPolygons = [];
    };

    MapCore.prototype.clearCustomPolygons = function () {
        this.customPolygons.forEach(function (polygon) { polygon.setMap(null); });
        this.customPolygons = [];
    };

    MapCore.prototype._normalizeLngLatPoint = function (pt) {
        var lng = NaN;
        var lat = NaN;
        if (Array.isArray(pt) && pt.length >= 2) {
            lng = Number(pt[0]);
            lat = Number(pt[1]);
        } else if (pt && typeof pt === 'object') {
            if (typeof pt.getLng === 'function' && typeof pt.getLat === 'function') {
                lng = Number(pt.getLng());
                lat = Number(pt.getLat());
            } else if (Object.prototype.hasOwnProperty.call(pt, 'lng') && Object.prototype.hasOwnProperty.call(pt, 'lat')) {
                lng = Number(pt.lng);
                lat = Number(pt.lat);
            } else if (Object.prototype.hasOwnProperty.call(pt, 'lon') && Object.prototype.hasOwnProperty.call(pt, 'lat')) {
                lng = Number(pt.lon);
                lat = Number(pt.lat);
            }
        } else if (typeof pt === 'string') {
            var parts = pt.split(',');
            if (parts.length >= 2) {
                lng = Number(parts[0].trim());
                lat = Number(parts[1].trim());
            }
        }
        if (!Number.isFinite(lng) || !Number.isFinite(lat)) return null;
        return [lng, lat];
    };

    MapCore.prototype._normalizePathPoints = function (path, minPoints) {
        var required = Number.isFinite(Number(minPoints)) ? Math.max(2, Math.floor(Number(minPoints))) : 2;
        var out = [];
        (Array.isArray(path) ? path : []).forEach(function (pt) {
            var norm = this._normalizeLngLatPoint(pt);
            if (norm) out.push(norm);
        }, this);
        return out.length >= required ? out : [];
    };

    MapCore.prototype._getTiandituContainer = function () {
        if (!this.tiandituContainerId || typeof document === 'undefined') return null;
        return document.getElementById(this.tiandituContainerId);
    };

    MapCore.prototype._toggleTiandituContainer = function (visible) {
        var el = this._getTiandituContainer();
        if (!el) return;
        el.style.display = visible ? 'block' : 'none';
    };

    MapCore.prototype._resizeTiandituMap = function () {
        if (!this.tiandituMap || !this.tiandituMap.checkResize) return;
        try {
            this.tiandituMap.checkResize();
        } catch (err) {
            console.warn('[MapCore] T.Map resize failed:', err);
        }
    };

    MapCore.prototype._ensureBlankTileLayer = function () {
        if (this._blankTileLayer) return this._blankTileLayer;
        var transparentPng = 'data:image/png;base64,'
            + 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO2p3nQAAAAASUVORK5CYII=';
        this._blankTileLayer = new AMap.TileLayer({
            zIndex: 0,
            opacity: 1,
            getTileUrl: function () {
                return transparentPng;
            }
        });
        return this._blankTileLayer;
    };

    MapCore.prototype._buildTiandituWmtsTileUrl = function (layerName, x, y, z) {
        if (!this.tiandituKey) return '';
        return 'https://t0.tianditu.gov.cn/' + layerName + '_w/wmts'
            + '?SERVICE=WMTS'
            + '&REQUEST=GetTile'
            + '&VERSION=1.0.0'
            + '&LAYER=' + layerName
            + '&STYLE=default'
            + '&TILEMATRIXSET=w'
            + '&FORMAT=tiles'
            + '&TILEMATRIX=' + z
            + '&TILEROW=' + y
            + '&TILECOL=' + x
            + '&tk=' + encodeURIComponent(this.tiandituKey);
    };

    MapCore.prototype._ensureTiandituWmtsLayers = function () {
        if (!this.tiandituKey) return false;
        if (this._tdtVecLayer && this._tdtCvaLayer) return true;
        var self = this;
        try {
            if (!this._tdtVecLayer) {
                this._tdtVecLayer = new AMap.TileLayer({
                    zIndex: 0,
                    opacity: 1,
                    getTileUrl: function (x, y, z) {
                        return self._buildTiandituWmtsTileUrl('vec', x, y, z);
                    }
                });
            }
            if (!this._tdtCvaLayer) {
                this._tdtCvaLayer = new AMap.TileLayer({
                    zIndex: 1,
                    opacity: 1,
                    getTileUrl: function (x, y, z) {
                        return self._buildTiandituWmtsTileUrl('cva', x, y, z);
                    }
                });
            }
        } catch (err) {
            console.warn('[MapCore] Failed to create TianDiTu WMTS layers:', err);
            this._tdtVecLayer = null;
            this._tdtCvaLayer = null;
            return false;
        }
        return !!(this._tdtVecLayer && this._tdtCvaLayer);
    };

    MapCore.prototype._ensureTiandituMap = function () {
        if (this.tiandituMap) return true;
        if (!(window.T && window.T.Map && window.T.LngLat)) {
            return false;
        }
        var container = this._getTiandituContainer();
        if (!container) return false;
        container.innerHTML = '';
        try {
            this.tiandituMap = new T.Map(this.tiandituContainerId);
            this.tiandituMap.centerAndZoom(
                new T.LngLat(this.center.lng, this.center.lat),
                Math.round(this.zoom || 13)
            );
            if (this.tiandituMap.setMinZoom) {
                this.tiandituMap.setMinZoom(this._tiandituZooms[0]);
            }
            if (this.tiandituMap.setMaxZoom) {
                this.tiandituMap.setMaxZoom(this._tiandituZooms[1]);
            }
            return true;
        } catch (err) {
            console.warn('[MapCore] Failed to create T.Map:', err);
            this.tiandituMap = null;
            return false;
        }
    };

    MapCore.prototype._syncTiandituViewFromAMap = function () {
        if (!this.tiandituMap || !this.map || !(window.T && window.T.LngLat)) return;
        if (!(this.map.getCenter && this.map.getZoom && this.tiandituMap.centerAndZoom)) return;
        this._resizeTiandituMap();
        var center = this.map.getCenter();
        if (!center || !center.getLng || !center.getLat) return;
        var zoom = this.map.getZoom();
        if (typeof zoom !== 'number') return;
        this.tiandituMap.centerAndZoom(
            new T.LngLat(center.getLng(), center.getLat()),
            Math.round(zoom)
        );
    };

    MapCore.prototype._applyAmapBasemap = function () {
        this._toggleTiandituContainer(false);
        if (this.map.setZooms) {
            this.map.setZooms(this._defaultZooms);
        }
        if (!this._amapTileLayer) {
            this._amapTileLayer = new AMap.TileLayer({ zIndex: 0, opacity: 1 });
        }
        if (this.map.setLayers) {
            this.map.setLayers([this._amapTileLayer]);
        } else {
            this._amapTileLayer.setMap(this.map);
        }
    };

    MapCore.prototype.setBasemapSource = function (source) {
        this.basemapSource = ['amap', 'osm', 'tianditu'].indexOf(source) >= 0 ? source : 'amap';
        this.lastBasemapError = null;
        if (!this.map) {
            this.lastBasemapError = {
                code: 'map-not-ready',
                message: 'Map is not initialized.'
            };
            return {
                ok: false,
                source: this.basemapSource,
                code: this.lastBasemapError.code,
                message: this.lastBasemapError.message
            };
        }

        if (this.basemapSource === 'osm') {
            this._toggleTiandituContainer(false);
            if (this.map.setZooms) {
                this.map.setZooms(this._defaultZooms);
            }
            if (!this._osmTileLayer) {
                this._osmTileLayer = new AMap.TileLayer({
                    zIndex: 0,
                    opacity: 1,
                    getTileUrl: function (x, y, z) {
                        return 'https://tile.openstreetmap.org/' + z + '/' + x + '/' + y + '.png';
                    }
                });
            }
            if (this.map.setLayers) {
                this.map.setLayers([this._osmTileLayer]);
            } else {
                this._osmTileLayer.setMap(this.map);
            }
            return { ok: true, source: 'osm' };
        }

        if (this.basemapSource === 'tianditu') {
            if (!this.tiandituKey) {
                console.warn('[MapCore] TIANDITU_KEY is empty.');
                this.lastBasemapError = {
                    code: 'missing-key',
                    message: 'TIANDITU_KEY is empty.'
                };
                return {
                    ok: false,
                    source: 'tianditu',
                    code: this.lastBasemapError.code,
                    message: this.lastBasemapError.message
                };
            } else {
                this._toggleTiandituContainer(false);
                if (!this._ensureTiandituWmtsLayers()) {
                    console.warn('[MapCore] TianDiTu WMTS layers are not ready.');
                    this.lastBasemapError = {
                        code: 'wmts-layer-init-failed',
                        message: 'TianDiTu WMTS layers are not ready.'
                    };
                    return {
                        ok: false,
                        source: 'tianditu',
                        code: this.lastBasemapError.code,
                        message: this.lastBasemapError.message
                    };
                } else {
                    if (this.map.setZooms) {
                        this.map.setZooms(this._tiandituZooms);
                    }
                    if (this.map.getZoom && this.map.setZoom) {
                        var currentZoom = this.map.getZoom();
                        if (typeof currentZoom === 'number' && currentZoom > this._tiandituZooms[1]) {
                            this.map.setZoom(this._tiandituZooms[1]);
                        }
                    }
                    if (this.map.setLayers) {
                        this.map.setLayers([this._tdtVecLayer, this._tdtCvaLayer]);
                    } else {
                        this._tdtVecLayer.setMap(this.map);
                        this._tdtCvaLayer.setMap(this.map);
                    }
                    return { ok: true, source: 'tianditu' };
                }
            }
        }

        this._applyAmapBasemap();
        return { ok: true, source: 'amap' };
    };

    MapCore.prototype.setBasemapMuted = function (muted) {
        this.basemapMuted = !!muted;
        if (!this.map) return;

        var opacity = this.basemapMuted ? 0 : 1;
        this._toggleTiandituContainer(false);

        // Do not replace map layer stack in simplify mode.
        // Replacing layers may drop analysis overlays (e.g. road syntax result lines).
        if (this._amapTileLayer && this._amapTileLayer.setOpacity) {
            this._amapTileLayer.setOpacity(opacity);
        }
        if (this._osmTileLayer && this._osmTileLayer.setOpacity) {
            this._osmTileLayer.setOpacity(opacity);
        }
        if (this._tdtVecLayer && this._tdtVecLayer.setOpacity) {
            this._tdtVecLayer.setOpacity(opacity);
        }
        if (this._tdtCvaLayer && this._tdtCvaLayer.setOpacity) {
            this._tdtCvaLayer.setOpacity(opacity);
        }

        if (this.basemapSource === 'amap' && this.map.setFeatures) {
            this.map.setFeatures(this.basemapMuted ? [] : ['bg', 'point', 'road', 'building']);
        }

        this._applyAnalysisBackdrop();
    };

    MapCore.prototype._resolveLocaApi = function () {
        if (window.Loca && typeof window.Loca.LineLayer === 'function') {
            return window.Loca;
        }
        var amapLoca = window.AMap && window.AMap.Loca;
        if (amapLoca && typeof amapLoca.LineLayer === 'function') {
            return amapLoca;
        }
        return null;
    };

    MapCore.prototype._extractAmapKeyFromScripts = function () {
        var scripts = document.querySelectorAll('script[src*="webapi.amap.com/maps"]');
        for (var i = 0; i < scripts.length; i += 1) {
            var src = String((scripts[i] && scripts[i].src) || '');
            if (!src) continue;
            try {
                var url = new URL(src, window.location.origin);
                var key = String(url.searchParams.get('key') || '').trim();
                if (key) return key;
            } catch (_) {
                var match = src.match(/[?&]key=([^&]+)/);
                if (match && match[1]) return decodeURIComponent(match[1]);
            }
        }
        return '';
    };

    MapCore.prototype.ensureGridLocaReady = function () {
        var self = this;
        if (this._resolveLocaApi()) {
            return Promise.resolve(true);
        }
        if (this._gridLocaLoaderPromise) {
            return this._gridLocaLoaderPromise;
        }
        this._gridLocaLoaderPromise = new Promise(function (resolve) {
            var settle = function (ok) {
                if (!ok) {
                    self.gridWebglPreferred = false;
                }
                resolve(!!ok);
            };
            var existing = document.querySelector('script[data-grid-loca-loader="1"]');
            if (existing) {
                var waitCount = 0;
                var timer = window.setInterval(function () {
                    waitCount += 1;
                    if (self._resolveLocaApi()) {
                        window.clearInterval(timer);
                        settle(true);
                        return;
                    }
                    if (waitCount >= 60) {
                        window.clearInterval(timer);
                        settle(false);
                    }
                }, 50);
                return;
            }
            var key = self._extractAmapKeyFromScripts();
            if (!key) {
                settle(false);
                return;
            }
            var script = document.createElement('script');
            script.async = true;
            script.defer = true;
            script.setAttribute('data-grid-loca-loader', '1');
            script.src = 'https://webapi.amap.com/loca?v=1.3.2&key=' + encodeURIComponent(key);
            var timeoutId = window.setTimeout(function () {
                settle(!!self._resolveLocaApi());
            }, 5000);
            script.onload = function () {
                window.clearTimeout(timeoutId);
                settle(!!self._resolveLocaApi());
            };
            script.onerror = function () {
                window.clearTimeout(timeoutId);
                settle(false);
            };
            document.head.appendChild(script);
        }).finally(function () {
            self._gridLocaLoaderPromise = null;
        });
        return this._gridLocaLoaderPromise;
    };

    MapCore.prototype._toRgbaColor = function (color, opacity) {
        var alpha = Number(opacity);
        if (!Number.isFinite(alpha)) alpha = 1;
        alpha = Math.max(0, Math.min(1, alpha));
        var text = String(color || '#000000').trim();
        if (text.indexOf('rgba(') === 0 || text.indexOf('hsla(') === 0) return text;
        if (text.indexOf('rgb(') === 0 || text.indexOf('hsl(') === 0) {
            return text
                .replace(/^rgb\(/i, 'rgba(')
                .replace(/\)\s*$/, ',' + alpha + ')')
                .replace(/^hsl\(/i, 'hsla(')
                .replace(/\)\s*$/, ',' + alpha + ')');
        }
        var hex = text.replace('#', '');
        if (hex.length === 3) {
            hex = hex[0] + hex[0] + hex[1] + hex[1] + hex[2] + hex[2];
        }
        if (hex.length !== 6) {
            return 'rgba(0,0,0,' + alpha + ')';
        }
        var r = parseInt(hex.slice(0, 2), 16);
        var g = parseInt(hex.slice(2, 4), 16);
        var b = parseInt(hex.slice(4, 6), 16);
        if (!Number.isFinite(r) || !Number.isFinite(g) || !Number.isFinite(b)) {
            return 'rgba(0,0,0,' + alpha + ')';
        }
        return 'rgba(' + r + ',' + g + ',' + b + ',' + alpha + ')';
    };

    MapCore.prototype._buildGridWebglSources = function (features, cfg) {
        var strokeColor = cfg.strokeColor || '#1e88e5';
        var strokeWeight = typeof cfg.strokeWeight === 'number' ? cfg.strokeWeight : 1.4;
        var fillColor = cfg.fillColor || '#42a5f5';
        var fillOpacity = typeof cfg.fillOpacity === 'number' ? cfg.fillOpacity : 0.2;
        var fillFeatures = [];
        var borderFeatures = [];
        var featureMap = {};
        var featureList = [];
        for (var i = 0; i < (features || []).length; i += 1) {
            var feature = features[i];
            if (!feature || !feature.geometry) continue;
            var g = feature.geometry || {};
            if (g.type !== 'Polygon') continue;
            var rings = g.coordinates || [];
            if (!Array.isArray(rings) || !Array.isArray(rings[0]) || rings[0].length < 3) continue;
            var props = Object.assign({}, feature.properties || {});
            var fill = props.fillColor || fillColor;
            var fillOp = typeof props.fillOpacity === 'number' ? props.fillOpacity : fillOpacity;
            var stroke = props.strokeColor || strokeColor;
            var strokeOp = typeof props.strokeOpacity === 'number' ? props.strokeOpacity : 0.82;
            var sw = typeof props.strokeWeight === 'number' ? props.strokeWeight : strokeWeight;
            props.__fill_rgba = this._toRgbaColor(fill, fillOp);
            props.__stroke_rgba = this._toRgbaColor(stroke, strokeOp);
            props.__stroke_weight = sw;
            var fillFeature = {
                type: 'Feature',
                geometry: g,
                properties: props
            };
            fillFeatures.push(fillFeature);
            featureList.push(fillFeature);
            var h3Id = String(props.h3_id || '');
            if (h3Id) featureMap[h3Id] = fillFeature;
            for (var r = 0; r < rings.length; r += 1) {
                var ring = this._normalizePathPoints(rings[r], 3);
                if (!ring || ring.length < 2) continue;
                borderFeatures.push({
                    type: 'Feature',
                    geometry: { type: 'LineString', coordinates: ring },
                    properties: {
                        h3_id: h3Id,
                        __stroke_rgba: props.__stroke_rgba,
                        __stroke_weight: sw
                    }
                });
            }
        }
        return {
            fillCollection: {
                type: 'FeatureCollection',
                features: fillFeatures
            },
            borderCollection: {
                type: 'FeatureCollection',
                features: borderFeatures
            },
            featureMap: featureMap,
            featureList: featureList
        };
    };

    MapCore.prototype._clearGridWebglLayers = function () {
        var container = this.gridLocaContainer;
        if (container && this.gridLocaFillLayer && typeof container.remove === 'function') {
            try { container.remove(this.gridLocaFillLayer); } catch (_) { }
        }
        if (container && this.gridLocaBorderLayer && typeof container.remove === 'function') {
            try { container.remove(this.gridLocaBorderLayer); } catch (_) { }
        }
        if (this.gridLocaFillLayer && typeof this.gridLocaFillLayer.destroy === 'function') {
            try { this.gridLocaFillLayer.destroy(); } catch (_) { }
        }
        if (this.gridLocaBorderLayer && typeof this.gridLocaBorderLayer.destroy === 'function') {
            try { this.gridLocaBorderLayer.destroy(); } catch (_) { }
        }
        this.gridLocaFillLayer = null;
        this.gridLocaBorderLayer = null;
        this.gridWebglEnabled = false;
        this.gridFeatureMap = {};
        this.gridFeatureList = [];
    };

    MapCore.prototype._renderGridFeaturesWithWebgl = function (features, cfg) {
        if (!this.map || !this.gridWebglPreferred) return false;
        var locaApi = this._resolveLocaApi();
        if (
            !locaApi
            || typeof locaApi.Container !== 'function'
            || typeof locaApi.GeoJSONSource !== 'function'
            || typeof locaApi.PolygonLayer !== 'function'
            || typeof locaApi.LineLayer !== 'function'
        ) {
            return false;
        }
        var sourcePack = this._buildGridWebglSources(features, cfg || {});
        if (!sourcePack.fillCollection.features.length) return false;
        if (!this.gridLocaContainer) {
            this.gridLocaContainer = new locaApi.Container({ map: this.map });
        }
        this._clearGridWebglLayers();
        this.gridFeatureMap = sourcePack.featureMap;
        this.gridFeatureList = sourcePack.featureList;
        var fillSource = new locaApi.GeoJSONSource({ data: sourcePack.fillCollection });
        var fillLayer = new locaApi.PolygonLayer({
            zIndex: 80,
            opacity: 1,
            hasSide: false
        });
        fillLayer.setSource(fillSource);
        fillLayer.setStyle({
            topColor: function (index, feature) {
                var p = (feature && feature.properties) || {};
                return p.__fill_rgba || 'rgba(66,165,245,0.22)';
            },
            sideTopColor: 'rgba(0,0,0,0)',
            sideBottomColor: 'rgba(0,0,0,0)',
            height: 0
        });
        var borderSource = new locaApi.GeoJSONSource({ data: sourcePack.borderCollection });
        var borderLayer = new locaApi.LineLayer({
            zIndex: 86,
            opacity: 1
        });
        borderLayer.setSource(borderSource);
        borderLayer.setStyle({
            color: function (index, feature) {
                var p = (feature && feature.properties) || {};
                return p.__stroke_rgba || 'rgba(44,110,203,0.82)';
            },
            lineWidth: function (index, feature) {
                var p = (feature && feature.properties) || {};
                var w = Number(p.__stroke_weight);
                return Number.isFinite(w) ? w : 1;
            }
        });
        try { this.gridLocaContainer.add(fillLayer); } catch (_) { }
        try { this.gridLocaContainer.add(borderLayer); } catch (_) { }
        if (typeof fillLayer.render === 'function') {
            try { fillLayer.render(); } catch (_) { }
        }
        if (typeof borderLayer.render === 'function') {
            try { borderLayer.render(); } catch (_) { }
        }
        if (typeof this.gridLocaContainer.requestRender === 'function') {
            try { this.gridLocaContainer.requestRender(); } catch (_) { }
        }
        this.gridLocaFillLayer = fillLayer;
        this.gridLocaBorderLayer = borderLayer;
        this.gridWebglEnabled = true;
        return true;
    };

    MapCore.prototype.clearGridPolygons = function () {
        if (this._gridFocusAnimTimer) {
            window.clearInterval(this._gridFocusAnimTimer);
            this._gridFocusAnimTimer = null;
        }
        if (this.focusedGridOverlay && this.focusedGridOverlay.setMap) {
            this.focusedGridOverlay.setMap(null);
        }
        this.focusedGridOverlay = null;
        this.gridPolygons.forEach(function (polygon) { polygon.setMap(null); });
        this.gridPolygons = [];
        this.gridStructureBoundaryOverlays.forEach(function (overlay) {
            if (overlay && overlay.setMap) overlay.setMap(null);
        });
        this.gridStructureBoundaryOverlays = [];
        this.gridStructureSymbolOverlays.forEach(function (overlay) {
            if (overlay && overlay.setMap) overlay.setMap(null);
        });
        this.gridStructureSymbolOverlays = [];
        this.gridPolygonMap = {};
        this.gridFeatureMap = {};
        this.gridFeatureList = [];
        this._clearGridWebglLayers();
        this.focusedGridPolygon = null;
        this._gridFocusViewBeforeLock = null;
    };

    MapCore.prototype._createSpatialFeatureOverlays = function (feature, opts) {
        var cfg = opts || {};
        var target = feature && feature.type === 'Feature' ? feature : null;
        var geometry = target && target.geometry;
        if (!this.map || !target || !geometry || !window.AMap) return [];
        var coordinates = geometry.coordinates;
        var overlays = [];
        var self = this;
        var strokeColor = cfg.strokeColor || '#0f766e';
        var fillColor = cfg.fillColor || strokeColor || '#14b8a6';
        var fillOpacity = typeof cfg.fillOpacity === 'number' ? cfg.fillOpacity : 0.18;
        var markerColor = /^#[0-9a-f]{6}$/i.test(fillColor) ? fillColor : '#0f766e';
        var markerContent = '<span aria-hidden="true" style="display:block;width:14px;height:14px;border:2px solid #fff;border-radius:50%;background:' + markerColor + ';box-shadow:0 1px 4px rgba(15,23,42,.35)"></span>';
        var addOverlay = function (overlay) {
            if (overlay && typeof overlay.on === 'function' && typeof cfg.onClick === 'function') {
                overlay.on('click', cfg.onClick);
            }
            if (overlay && typeof overlay.setMap === 'function') overlay.setMap(self.map);
            if (overlay) overlays.push(overlay);
        };
        var polygon = function (rings) {
            if (!Array.isArray(rings) || !rings.length) return;
            addOverlay(new AMap.Polygon({
                path: rings,
                strokeColor: strokeColor,
                strokeWeight: cfg.strokeWeight || 4,
                strokeOpacity: 0.95,
                fillColor: fillColor,
                fillOpacity: fillOpacity,
                zIndex: cfg.zIndex || 140,
            }));
        };
        var line = function (path) {
            if (!Array.isArray(path) || !path.length) return;
            addOverlay(new AMap.Polyline({
                path: path,
                strokeColor: strokeColor,
                strokeWeight: cfg.strokeWeight || 6,
                strokeOpacity: 0.95,
                lineJoin: 'round',
                lineCap: 'round',
                zIndex: cfg.zIndex || 140,
            }));
        };
        if (geometry.type === 'Point') {
            addOverlay(new AMap.Marker({ position: coordinates, content: markerContent, zIndex: cfg.zIndex || 140 }));
        } else if (geometry.type === 'MultiPoint') {
            (coordinates || []).forEach(function (point) { addOverlay(new AMap.Marker({ position: point, content: markerContent, zIndex: cfg.zIndex || 140 })); });
        } else if (geometry.type === 'LineString') {
            line(coordinates);
        } else if (geometry.type === 'MultiLineString') {
            (coordinates || []).forEach(line);
        } else if (geometry.type === 'Polygon') {
            polygon(coordinates);
        } else if (geometry.type === 'MultiPolygon') {
            (coordinates || []).forEach(polygon);
        }
        return overlays;
    };

    MapCore.prototype.clearSpatialFeatureFocus = function () {
        (this.focusedSpatialOverlays || []).forEach(function (overlay) {
            if (overlay && typeof overlay.setMap === 'function') overlay.setMap(null);
        });
        this.focusedSpatialOverlays = [];
    };

    MapCore.prototype.clearSpatialPresentation = function () {
        (this.spatialPresentationOverlays || []).forEach(function (overlay) {
            if (overlay && typeof overlay.setMap === 'function') overlay.setMap(null);
        });
        this.spatialPresentationOverlays = [];
    };

    MapCore.prototype.showSpatialPresentation = function (items, opts) {
        var cfg = opts || {};
        var overlays = [];
        var self = this;
        this.clearSpatialPresentation();
        (Array.isArray(items) ? items : []).forEach(function (item) {
            if (!item || !item.feature) return;
            var itemOverlays = self._createSpatialFeatureOverlays(item.feature, {
                strokeColor: item.color || cfg.strokeColor,
                fillColor: item.color || cfg.fillColor,
                fillOpacity: typeof item.fillOpacity === 'number' ? item.fillOpacity : 0.24,
                strokeWeight: item.strokeWeight || 4,
                zIndex: item.zIndex || 132,
                onClick: typeof cfg.onClick === 'function' ? function () { cfg.onClick(item); } : null,
            });
            overlays = overlays.concat(itemOverlays);
        });
        this.spatialPresentationOverlays = overlays;
        if (overlays.length && cfg.fitView !== false && typeof this.map.setFitView === 'function') {
            this.map.setFitView(overlays, false, [48, 48, 48, 48]);
        }
        return overlays.length;
    };

    MapCore.prototype.focusSpatialFeature = function (feature, opts) {
        var cfg = opts || {};
        var overlays = this._createSpatialFeatureOverlays(feature, cfg);
        if (!overlays.length) return false;
        this.clearSpatialFeatureFocus();
        this.focusedSpatialOverlays = overlays;
        if (cfg.fitView !== false && typeof this.map.setFitView === 'function') {
            this.map.setFitView(overlays, false, [48, 48, 48, 48]);
        }
        return true;
    };

    MapCore.prototype.setCustomPolygons = function (pathsList) {
        var self = this;
        this.clearCustomPolygons();
        (pathsList || []).forEach(function (path) {
            var normalizedPath = self._normalizePathPoints(path, 3);
            if (!normalizedPath.length) return;
            var polygon = new AMap.Polygon({
                path: normalizedPath,
                strokeColor: '#ff6f00',
                strokeWeight: 2,
                strokeOpacity: 0.9,
                fillColor: '#ff6f00',
                fillOpacity: 0,
                clickable: false,
                bubble: true
            });
            polygon.setMap(self.map);
            self.customPolygons.push(polygon);
        });
        this.updateFitView();
    };

    MapCore.prototype._normalizeEdgePoint = function (pt, precision) {
        var lng = NaN;
        var lat = NaN;
        if (Array.isArray(pt) && pt.length >= 2) {
            lng = Number(pt[0]);
            lat = Number(pt[1]);
        } else if (pt && typeof pt === 'object') {
            if (typeof pt.getLng === 'function' && typeof pt.getLat === 'function') {
                lng = Number(pt.getLng());
                lat = Number(pt.getLat());
            } else if (Object.prototype.hasOwnProperty.call(pt, 'lng') && Object.prototype.hasOwnProperty.call(pt, 'lat')) {
                lng = Number(pt.lng);
                lat = Number(pt.lat);
            } else if (Object.prototype.hasOwnProperty.call(pt, 'lon') && Object.prototype.hasOwnProperty.call(pt, 'lat')) {
                lng = Number(pt.lon);
                lat = Number(pt.lat);
            }
        }
        if (!Number.isFinite(lng) || !Number.isFinite(lat)) return null;
        var p = Math.max(0, Number.isFinite(Number(precision)) ? Math.floor(Number(precision)) : 7);
        var factor = Math.pow(10, p);
        return [
            Math.round(lng * factor) / factor,
            Math.round(lat * factor) / factor
        ];
    };

    MapCore.prototype._buildEdgeKey = function (p1, p2) {
        if (!Array.isArray(p1) || !Array.isArray(p2) || p1.length < 2 || p2.length < 2) return '';
        var first = p1;
        var second = p2;
        if (p1[0] > p2[0] || (p1[0] === p2[0] && p1[1] > p2[1])) {
            first = p2;
            second = p1;
        }
        return String(first[0]) + ',' + String(first[1]) + '|' + String(second[0]) + ',' + String(second[1]);
    };

    MapCore.prototype._resolveLisaSubtype = function (props) {
        var p = props || {};
        var lisaCluster = String(p.lisa_cluster || 'NS').toUpperCase();
        if (lisaCluster === 'HH' || lisaCluster === 'HL' || lisaCluster === 'LH' || lisaCluster === 'LL') {
            return lisaCluster;
        }
        return null;
    };

    MapCore.prototype._getStructureBoundaryBucket = function (sourceType, props) {
        var p = props || {};
        if (sourceType === 'gi') {
            var giColorMap = {
                core_hotspot: '#991b1b',
                secondary_hotspot: '#dc2626',
                core_coldspot: '#1e3a8a',
                secondary_coldspot: '#2563eb'
            };
            var giType = String(p.spatial_structure_type || 'ns');
            var giColor = giColorMap[giType] || null;
            if (!giColor) return null;
            return {
                key: 'gi:' + giType,
                subtype: giType,
                color: giColor
            };
        }
        if (sourceType === 'lisa') {
            var lisaColorMap = {
                HH: '#facc15',
                HL: '#e879f9',
                LH: '#10b981',
                LL: '#22d3ee'
            };
            var lisaCluster = this._resolveLisaSubtype(p);
            var lisaColor = lisaColorMap[lisaCluster] || null;
            if (!lisaColor) return null;
            return {
                key: 'lisa:' + lisaCluster,
                subtype: lisaCluster,
                color: lisaColor
            };
        }
        return null;
    };

    MapCore.prototype._extractOuterEdges = function (features, sourceType, subtypeKey) {
        var edgeOwners = {};
        var self = this;
        var normalizedSubtype = subtypeKey ? String(subtypeKey).toUpperCase() : '';
        var candidateCells = {};
        var seenCellIds = {};
        (features || []).forEach(function (feature, featureIdx) {
            if (!feature || !feature.geometry || feature.geometry.type !== 'Polygon') return;
            var rings = feature.geometry.coordinates || [];
            var path = rings[0];
            if (!Array.isArray(path) || path.length < 3) return;
            var props = feature.properties || {};
            var bucket = self._getStructureBoundaryBucket(sourceType, props);
            if (!bucket) return;
            if (normalizedSubtype && String(bucket.subtype || '').toUpperCase() !== normalizedSubtype) return;
            var candidateKey = String(props.h3_id || '');
            if (!candidateKey) candidateKey = '__idx_' + String(featureIdx);
            if (seenCellIds[candidateKey]) return;
            seenCellIds[candidateKey] = 1;
            candidateCells[candidateKey] = 1;

            var points = path.slice();
            var firstNorm = self._normalizeEdgePoint(points[0], 7);
            var lastNorm = self._normalizeEdgePoint(points[points.length - 1], 7);
            if (
                firstNorm && lastNorm
                && firstNorm[0] === lastNorm[0]
                && firstNorm[1] === lastNorm[1]
            ) {
                points = points.slice(0, points.length - 1);
            }
            if (!Array.isArray(points) || points.length < 3) return;

            var seenKeys = {};
            for (var idx = 0; idx < points.length; idx += 1) {
                var nextIdx = (idx + 1) % points.length;
                var p1 = self._normalizeEdgePoint(points[idx], 7);
                var p2 = self._normalizeEdgePoint(points[nextIdx], 7);
                if (!p1 || !p2) continue;
                if (p1[0] === p2[0] && p1[1] === p2[1]) continue;
                var key = self._buildEdgeKey(p1, p2);
                if (!key || seenKeys[key]) continue;
                seenKeys[key] = true;
                var bucketEdgeKey = bucket.key + '::' + key;
                if (!edgeOwners[bucketEdgeKey]) edgeOwners[bucketEdgeKey] = [];
                edgeOwners[bucketEdgeKey].push({
                    path: [p1, p2],
                    color: bucket.color,
                });
            }
        });

        var outerEdges = [];
        Object.keys(edgeOwners).forEach(function (key) {
            var owners = edgeOwners[key] || [];
            if (owners.length === 1) outerEdges.push(owners[0]);
        });
        return {
            edges: outerEdges,
            candidateCount: Object.keys(candidateCells).length
        };
    };

    MapCore.prototype._getNightlightBoundaryBucket = function (props, fieldName, styleMap) {
        var p = props || {};
        var safeField = String(fieldName || '').trim();
        if (!safeField) return null;
        var subtype = String(p[safeField] || '').trim();
        if (!subtype) return null;
        var styleSpec = styleMap && styleMap[subtype];
        if (!styleSpec) return null;
        return {
            key: 'nightlight:' + safeField + ':' + subtype,
            subtype: subtype,
            color: styleSpec.strokeColor || styleSpec.color || '#f8fafc'
        };
    };

    MapCore.prototype._extractNightlightOuterEdges = function (features, fieldName, subtypeKey, styleMap) {
        var edgeOwners = {};
        var self = this;
        var normalizedSubtype = String(subtypeKey || '').trim();
        var candidateCells = {};
        var seenCellIds = {};
        (features || []).forEach(function (feature, featureIdx) {
            if (!feature || !feature.geometry || feature.geometry.type !== 'Polygon') return;
            var rings = feature.geometry.coordinates || [];
            var path = rings[0];
            if (!Array.isArray(path) || path.length < 3) return;
            var props = feature.properties || {};
            var bucket = self._getNightlightBoundaryBucket(props, fieldName, styleMap);
            if (!bucket) return;
            if (normalizedSubtype && String(bucket.subtype || '') !== normalizedSubtype) return;

            var candidateKey = String(props.h3_id || props.cell_id || '');
            if (!candidateKey) candidateKey = '__idx_' + String(featureIdx);
            if (seenCellIds[candidateKey]) return;
            seenCellIds[candidateKey] = 1;
            candidateCells[candidateKey] = 1;

            var points = path.slice();
            var firstNorm = self._normalizeEdgePoint(points[0], 7);
            var lastNorm = self._normalizeEdgePoint(points[points.length - 1], 7);
            if (
                firstNorm && lastNorm
                && firstNorm[0] === lastNorm[0]
                && firstNorm[1] === lastNorm[1]
            ) {
                points = points.slice(0, points.length - 1);
            }
            if (!Array.isArray(points) || points.length < 3) return;

            var seenKeys = {};
            for (var idx = 0; idx < points.length; idx += 1) {
                var nextIdx = (idx + 1) % points.length;
                var p1 = self._normalizeEdgePoint(points[idx], 7);
                var p2 = self._normalizeEdgePoint(points[nextIdx], 7);
                if (!p1 || !p2) continue;
                if (p1[0] === p2[0] && p1[1] === p2[1]) continue;
                var key = self._buildEdgeKey(p1, p2);
                if (!key || seenKeys[key]) continue;
                seenKeys[key] = true;
                var bucketEdgeKey = bucket.key + '::' + key;
                if (!edgeOwners[bucketEdgeKey]) edgeOwners[bucketEdgeKey] = [];
                edgeOwners[bucketEdgeKey].push({
                    path: [p1, p2],
                    color: bucket.color,
                    subtype: bucket.subtype,
                });
            }
        });

        var outerEdges = [];
        Object.keys(edgeOwners).forEach(function (key) {
            var owners = edgeOwners[key] || [];
            if (owners.length === 1) outerEdges.push(owners[0]);
        });
        return {
            edges: outerEdges,
            candidateCount: Object.keys(candidateCells).length
        };
    };

    MapCore.prototype._renderStructureBoundaryEdges = function (edgeSegments, styleSpec) {
        var self = this;
        var spec = styleSpec || {};
        if (!this.map) return;
        (edgeSegments || []).forEach(function (segment) {
            if (!segment || !Array.isArray(segment.path) || segment.path.length < 2) return;
            var styleType = String(spec.strokeStyle || 'solid').toLowerCase();
            var useDashed = styleType === 'dashed' || styleType === 'dotted';
            var strokeDasharray = spec.strokeDasharray;
            if (!Array.isArray(strokeDasharray) || strokeDasharray.length < 2) {
                strokeDasharray = styleType === 'dotted' ? [2, 6] : [10, 8];
            }
            var zIndex = typeof spec.zIndex === 'number' ? spec.zIndex : 160;
            var haloWeight = typeof spec.haloWeight === 'number' ? spec.haloWeight : 0;
            if (haloWeight > 0) {
                var haloLine = new AMap.Polyline({
                    path: segment.path,
                    strokeColor: spec.haloColor || '#ffffff',
                    strokeWeight: haloWeight,
                    strokeOpacity: typeof spec.haloOpacity === 'number' ? spec.haloOpacity : 0.95,
                    strokeStyle: 'solid',
                    lineJoin: 'round',
                    lineCap: 'round',
                    zIndex: zIndex - 1,
                    bubble: true,
                    clickable: false
                });
                haloLine.setMap(self.map);
                self.gridStructureBoundaryOverlays.push(haloLine);
            }
            var polyline = new AMap.Polyline({
                path: segment.path,
                strokeColor: spec.strokeColor || segment.color || '#111827',
                strokeWeight: typeof spec.strokeWeight === 'number' ? spec.strokeWeight : 4,
                strokeOpacity: typeof spec.strokeOpacity === 'number' ? spec.strokeOpacity : 1,
                strokeStyle: useDashed ? 'dashed' : 'solid',
                strokeDasharray: useDashed ? strokeDasharray : undefined,
                lineJoin: 'round',
                lineCap: 'round',
                zIndex: zIndex,
                bubble: true,
                clickable: false
            });
            polyline.setMap(self.map);
            self.gridStructureBoundaryOverlays.push(polyline);
        });
    };

    MapCore.prototype._buildClosedRingsFromEdges = function (edgeSegments) {
        var segments = Array.isArray(edgeSegments) ? edgeSegments : [];
        if (!segments.length) return [];

        var pointByKey = {};
        var adjacency = {};
        var edgeMap = {};
        var self = this;

        var pointKey = function (pt) {
            if (!Array.isArray(pt) || pt.length < 2) return '';
            return String(pt[0]) + ',' + String(pt[1]);
        };

        var addNeighbor = function (fromKey, toKey) {
            if (!adjacency[fromKey]) adjacency[fromKey] = [];
            if (adjacency[fromKey].indexOf(toKey) < 0) adjacency[fromKey].push(toKey);
        };

        segments.forEach(function (segment) {
            if (!segment || !Array.isArray(segment.path) || segment.path.length < 2) return;
            var p1 = self._normalizeEdgePoint(segment.path[0], 7);
            var p2 = self._normalizeEdgePoint(segment.path[1], 7);
            if (!p1 || !p2) return;
            if (p1[0] === p2[0] && p1[1] === p2[1]) return;
            var k1 = pointKey(p1);
            var k2 = pointKey(p2);
            if (!k1 || !k2) return;
            pointByKey[k1] = p1;
            pointByKey[k2] = p2;
            addNeighbor(k1, k2);
            addNeighbor(k2, k1);
            var eKey = self._buildEdgeKey(p1, p2);
            if (!eKey) return;
            edgeMap[eKey] = { a: k1, b: k2 };
        });

        var usedEdges = {};
        var edgeKeys = Object.keys(edgeMap);
        var rings = [];
        var maxStep = Math.max(32, edgeKeys.length * 2 + 8);

        edgeKeys.forEach(function (startEdgeKey) {
            if (usedEdges[startEdgeKey]) return;
            var edge = edgeMap[startEdgeKey];
            if (!edge) return;
            var startKey = edge.a;
            var prevKey = edge.a;
            var currKey = edge.b;
            var ring = [pointByKey[startKey], pointByKey[currKey]];
            usedEdges[startEdgeKey] = 1;

            var step = 0;
            while (step < maxStep && currKey !== startKey) {
                step += 1;
                var neighbors = adjacency[currKey] || [];
                if (!neighbors.length) break;

                var nextKey = null;
                for (var nIdx = 0; nIdx < neighbors.length; nIdx += 1) {
                    var candidate = neighbors[nIdx];
                    if (!candidate || candidate === prevKey) continue;
                    var cEdgeKey = self._buildEdgeKey(pointByKey[currKey], pointByKey[candidate]);
                    if (cEdgeKey && !usedEdges[cEdgeKey]) {
                        nextKey = candidate;
                        usedEdges[cEdgeKey] = 1;
                        break;
                    }
                }

                if (!nextKey) {
                    var closeEdgeKey = self._buildEdgeKey(pointByKey[currKey], pointByKey[startKey]);
                    if (
                        (adjacency[currKey] || []).indexOf(startKey) >= 0
                        && closeEdgeKey
                        && !usedEdges[closeEdgeKey]
                    ) {
                        nextKey = startKey;
                        usedEdges[closeEdgeKey] = 1;
                    } else {
                        break;
                    }
                }

                ring.push(pointByKey[nextKey]);
                prevKey = currKey;
                currKey = nextKey;
            }

            if (currKey === startKey && ring.length >= 4) {
                var first = ring[0];
                var last = ring[ring.length - 1];
                if (!last || first[0] !== last[0] || first[1] !== last[1]) {
                    ring.push([first[0], first[1]]);
                }
                rings.push(ring);
            }
        });

        return rings;
    };

    MapCore.prototype._renderStructureBoundaryRings = function (rings, styleSpec) {
        var self = this;
        var spec = styleSpec || {};
        if (!this.map) return;
        (rings || []).forEach(function (ringPath) {
            if (!Array.isArray(ringPath) || ringPath.length < 4) return;
            var styleType = String(spec.strokeStyle || 'solid').toLowerCase();
            var useDashed = styleType === 'dashed' || styleType === 'dotted';
            var strokeDasharray = spec.strokeDasharray;
            if (!Array.isArray(strokeDasharray) || strokeDasharray.length < 2) {
                strokeDasharray = styleType === 'dotted' ? [2, 6] : [10, 8];
            }
            var zIndex = typeof spec.zIndex === 'number' ? spec.zIndex : 160;
            var haloWeight = typeof spec.haloWeight === 'number' ? spec.haloWeight : 0;
            if (haloWeight > 0) {
                var haloLine = new AMap.Polyline({
                    path: ringPath,
                    strokeColor: spec.haloColor || '#ffffff',
                    strokeWeight: haloWeight,
                    strokeOpacity: typeof spec.haloOpacity === 'number' ? spec.haloOpacity : 0.95,
                    strokeStyle: 'solid',
                    lineJoin: 'round',
                    lineCap: 'round',
                    zIndex: zIndex - 1,
                    bubble: true,
                    clickable: false
                });
                haloLine.setMap(self.map);
                self.gridStructureBoundaryOverlays.push(haloLine);
            }
            var polyline = new AMap.Polyline({
                path: ringPath,
                strokeColor: spec.strokeColor || '#111827',
                strokeWeight: typeof spec.strokeWeight === 'number' ? spec.strokeWeight : 4,
                strokeOpacity: typeof spec.strokeOpacity === 'number' ? spec.strokeOpacity : 1,
                strokeStyle: useDashed ? 'dashed' : 'solid',
                strokeDasharray: useDashed ? strokeDasharray : undefined,
                lineJoin: 'round',
                lineCap: 'round',
                zIndex: zIndex,
                bubble: true,
                clickable: false
            });
            polyline.setMap(self.map);
            self.gridStructureBoundaryOverlays.push(polyline);
        });
    };

    MapCore.prototype._renderEdgeSymbols = function (edgeSegments, symbolSpec) {
        var self = this;
        if (!this.map) return 0;
        var spec = symbolSpec || {};
        var textSymbol = String(spec.text || '▲');
        var symbolCount = 0;
        (edgeSegments || []).forEach(function (segment) {
            if (!segment || !Array.isArray(segment.path) || segment.path.length < 2) return;
            var p1 = segment.path[0];
            var p2 = segment.path[1];
            if (!Array.isArray(p1) || !Array.isArray(p2) || p1.length < 2 || p2.length < 2) return;
            var mid = [
                (Number(p1[0]) + Number(p2[0])) / 2,
                (Number(p1[1]) + Number(p2[1])) / 2
            ];
            if (!Number.isFinite(mid[0]) || !Number.isFinite(mid[1])) return;
            var symbol = new AMap.Text({
                text: textSymbol,
                position: mid,
                anchor: 'center',
                clickable: false,
                bubble: true,
                style: {
                    border: 'none',
                    background: 'transparent',
                    color: spec.color || segment.color || '#0ea5a4',
                    fontSize: '12px',
                    fontWeight: '700',
                    lineHeight: '12px',
                    padding: '0',
                },
                zIndex: typeof spec.zIndex === 'number' ? spec.zIndex : 166
            });
            symbol.setMap(self.map);
            self.gridStructureSymbolOverlays.push(symbol);
            symbolCount += 1;
        });
        return symbolCount;
    };

    MapCore.prototype.setGridFeatures = function (features, style) {
        var self = this;
        var cfg = style || {};
        var strokeColor = cfg.strokeColor || '#1e88e5';
        var strokeWeight = typeof cfg.strokeWeight === 'number' ? cfg.strokeWeight : 1.4;
        var fillColor = cfg.fillColor || '#42a5f5';
        var fillOpacity = typeof cfg.fillOpacity === 'number' ? cfg.fillOpacity : 0;
        var clickable = cfg.clickable !== false;
        var bubble = cfg.bubble !== false;
        var showStructureBoundaryEdges = !!cfg.structureBoundaryEdges;
        var showStructureBoundaryGi = !!cfg.structureBoundaryGi;
        var showStructureBoundaryLisa = !!cfg.structureBoundaryLisa;
        var showStructureLisaSymbols = !!cfg.structureLisaSymbolMode;
        var structureBoundaryLineStyleMap = cfg.structureBoundaryLineStyleMap || {};
        var structureBoundaryDebug = !!cfg.structureBoundaryDebug;
        var nightlightBoundaryField = String(cfg.nightlightBoundaryField || '').trim();
        var nightlightBoundaryStyleMap = cfg.nightlightBoundaryStyleMap || {};
        var nightlightBoundaryOrder = Array.isArray(cfg.nightlightBoundaryOrder) ? cfg.nightlightBoundaryOrder : [];
        var nightlightBoundaryDebug = !!cfg.nightlightBoundaryDebug;
        var useWebglBatch = cfg.webglBatch !== false && this.gridWebglPreferred;
        var renderedByWebgl = false;
        var boundaryRenderStats = {
            enabled: showStructureBoundaryEdges,
            giOuterEdges: 0,
            lisaCandidateCells: { HH: 0, LL: 0, HL: 0, LH: 0 },
            lisaOuterEdges: { HH: 0, LL: 0, HL: 0, LH: 0 },
            lisaOuterRings: { HH: 0, LL: 0, HL: 0, LH: 0 },
            lisaSymbols: 0,
            nightlightRings: {},
        };

        this.clearGridPolygons();
        if (useWebglBatch) {
            renderedByWebgl = this._renderGridFeaturesWithWebgl(features, cfg);
        }
        if (!renderedByWebgl) {
            (features || []).forEach(function (feature) {
                if (!feature || !feature.geometry || feature.geometry.type !== 'Polygon') return;
                var rings = feature.geometry.coordinates || [];
                var path = self._normalizePathPoints(rings[0], 3);
                if (!Array.isArray(path) || path.length < 3) return;
                var props = feature.properties || {};
                var currentStrokeColor = props.strokeColor || strokeColor;
                var currentStrokeWeight = typeof props.strokeWeight === 'number' ? props.strokeWeight : strokeWeight;
                var currentFillColor = props.fillColor || fillColor;
                var currentFillOpacity = typeof props.fillOpacity === 'number' ? props.fillOpacity : fillOpacity;

                var polygon = new AMap.Polygon({
                    path: path,
                    strokeColor: currentStrokeColor,
                    strokeWeight: currentStrokeWeight,
                    strokeOpacity: 0.82,
                    fillColor: currentFillColor,
                    fillOpacity: currentFillOpacity,
                    zIndex: 80,
                    clickable: clickable,
                    bubble: bubble
                });
                polygon.__baseStyle = {
                    strokeColor: currentStrokeColor,
                    strokeWeight: currentStrokeWeight,
                    fillColor: currentFillColor,
                    fillOpacity: currentFillOpacity,
                    zIndex: 80,
                };
                polygon.__h3Id = props.h3_id || null;
                polygon.__props = Object.assign({}, props);
                if (polygon.__h3Id && typeof self.config.onGridFeatureClick === 'function' && polygon.on) {
                    polygon.on('click', function (evt) {
                        var lnglat = null;
                        if (evt && evt.lnglat && evt.lnglat.getLng && evt.lnglat.getLat) {
                            lnglat = [evt.lnglat.getLng(), evt.lnglat.getLat()];
                        }
                        self.config.onGridFeatureClick({
                            h3_id: polygon.__h3Id,
                            properties: Object.assign({}, polygon.__props || {}),
                            lnglat: lnglat
                        });
                    });
                }
                polygon.setMap(self.map);
                self.gridPolygons.push(polygon);
                if (polygon.__h3Id) {
                    self.gridPolygonMap[polygon.__h3Id] = polygon;
                }
            });
        }

        if (showStructureBoundaryEdges) {
            if (showStructureBoundaryGi) {
                var giExtraction = this._extractOuterEdges(features, 'gi', null);
                var giOuterEdges = giExtraction.edges || [];
                boundaryRenderStats.giOuterEdges = giOuterEdges.length;
                if (structureBoundaryDebug && typeof console !== 'undefined' && console.info) {
                    console.info('[MapCore] Gi* outer edges:', giOuterEdges.length);
                }
                this._renderStructureBoundaryEdges(giOuterEdges, {
                    strokeWeight: 7,
                    strokeOpacity: 1,
                    zIndex: 260
                });
            }
            if (showStructureBoundaryLisa) {
                var lisaDefaults = {
                    HH: { strokeStyle: 'solid', strokeWeight: 4, strokeOpacity: 1, zIndex: 262, strokeColor: '#facc15', haloWeight: 6, haloColor: '#ffffff', haloOpacity: 0.95 },
                    LL: { strokeStyle: 'dashed', strokeWeight: 4, strokeOpacity: 1, zIndex: 263, strokeColor: '#22d3ee', strokeDasharray: [10, 8], haloWeight: 6, haloColor: '#ffffff', haloOpacity: 0.95 },
                    HL: { strokeStyle: 'dashed', strokeWeight: 4, strokeOpacity: 1, zIndex: 264, strokeColor: '#e879f9', strokeDasharray: [4, 6], haloWeight: 6, haloColor: '#ffffff', haloOpacity: 0.95 },
                    LH: { strokeStyle: 'solid', strokeWeight: 4, strokeOpacity: 1, zIndex: 265, strokeColor: '#10b981', haloWeight: 6, haloColor: '#ffffff', haloOpacity: 0.95 }
                };
                var lisaSubtypes = ['HH', 'LL', 'HL', 'LH'];
                for (var sIdx = 0; sIdx < lisaSubtypes.length; sIdx += 1) {
                    var subtype = lisaSubtypes[sIdx];
                    var lisaExtraction = this._extractOuterEdges(features, 'lisa', subtype);
                    var lisaEdges = lisaExtraction.edges || [];
                    var lisaRings = this._buildClosedRingsFromEdges(lisaEdges);
                    boundaryRenderStats.lisaCandidateCells[subtype] = Number(lisaExtraction.candidateCount || 0);
                    boundaryRenderStats.lisaOuterEdges[subtype] = lisaEdges.length;
                    boundaryRenderStats.lisaOuterRings[subtype] = lisaRings.length;
                    if (structureBoundaryDebug && typeof console !== 'undefined' && console.info) {
                        console.info(
                            '[MapCore] LISA rings (' + subtype + '):',
                            lisaRings.length,
                            'edges:',
                            lisaEdges.length,
                            'candidates:',
                            boundaryRenderStats.lisaCandidateCells[subtype]
                        );
                    }
                    if (!lisaRings.length) continue;
                    var styleOverride = structureBoundaryLineStyleMap[subtype] || {};
                    var lineSpec = Object.assign({}, lisaDefaults[subtype], styleOverride);
                    this._renderStructureBoundaryRings(lisaRings, lineSpec);
                    if (showStructureLisaSymbols && subtype === 'LH') {
                        boundaryRenderStats.lisaSymbols += this._renderEdgeSymbols(lisaEdges, {
                            text: '▲',
                            color: lineSpec.strokeColor || '#0ea5a4',
                            zIndex: (typeof lineSpec.zIndex === 'number' ? lineSpec.zIndex : 165) + 1,
                        });
                    }
                }
            }
        }

        if (nightlightBoundaryField && nightlightBoundaryOrder.length && nightlightBoundaryStyleMap) {
            nightlightBoundaryOrder.forEach(function (subtypeKey) {
                var extraction = self._extractNightlightOuterEdges(
                    features,
                    nightlightBoundaryField,
                    subtypeKey,
                    nightlightBoundaryStyleMap
                );
                var rings = self._buildClosedRingsFromEdges(extraction.edges || []);
                boundaryRenderStats.nightlightRings[subtypeKey] = {
                    candidateCount: Number(extraction.candidateCount || 0),
                    edgeCount: Array.isArray(extraction.edges) ? extraction.edges.length : 0,
                    ringCount: rings.length,
                };
                if (nightlightBoundaryDebug && typeof console !== 'undefined' && console.info) {
                    console.info(
                        '[MapCore] Nightlight rings (' + subtypeKey + '):',
                        rings.length,
                        'edges:',
                        boundaryRenderStats.nightlightRings[subtypeKey].edgeCount,
                        'candidates:',
                        boundaryRenderStats.nightlightRings[subtypeKey].candidateCount
                    );
                }
                if (!rings.length) return;
                var lineSpec = Object.assign({}, nightlightBoundaryStyleMap[subtypeKey] || {});
                self._renderStructureBoundaryRings(rings, lineSpec);
            });
        }

        this.updateFitView();
        return boundaryRenderStats;
    };

    MapCore.prototype._restoreGridPolygonStyle = function (polygon) {
        if (!polygon || !polygon.__baseStyle) return;
        polygon.setOptions({
            strokeColor: polygon.__baseStyle.strokeColor,
            strokeWeight: polygon.__baseStyle.strokeWeight,
            fillColor: polygon.__baseStyle.fillColor,
            fillOpacity: polygon.__baseStyle.fillOpacity,
            zIndex: polygon.__baseStyle.zIndex
        });
    };

    MapCore.prototype._stopGridFocusAnimation = function () {
        if (this._gridFocusAnimTimer) {
            window.clearInterval(this._gridFocusAnimTimer);
            this._gridFocusAnimTimer = null;
        }
    };

    MapCore.prototype._mixHexColor = function (fromHex, toHex, t) {
        var f = String(fromHex || '#22d3ee').replace('#', '');
        var to = String(toHex || '#ffffff').replace('#', '');
        if (f.length !== 6 || to.length !== 6) return fromHex || '#22d3ee';
        var clampT = Math.max(0, Math.min(1, t || 0));
        var fr = parseInt(f.substring(0, 2), 16);
        var fg = parseInt(f.substring(2, 4), 16);
        var fb = parseInt(f.substring(4, 6), 16);
        var tr = parseInt(to.substring(0, 2), 16);
        var tg = parseInt(to.substring(2, 4), 16);
        var tb = parseInt(to.substring(4, 6), 16);
        var rr = Math.round(fr + (tr - fr) * clampT);
        var rg = Math.round(fg + (tg - fg) * clampT);
        var rb = Math.round(fb + (tb - fb) * clampT);
        var hex = '#' + [rr, rg, rb].map(function (v) {
            var s = v.toString(16);
            return s.length === 1 ? '0' + s : s;
        }).join('');
        return hex;
    };

    MapCore.prototype._runGridFocusPulse = function (polygon, cfg) {
        this._stopGridFocusAnimation();
        if (!polygon) return;
        var baseStroke = cfg.strokeColor || '#22d3ee';
        var glowStroke = cfg.pulseColor || '#ecfeff';
        var baseWeight = typeof cfg.strokeWeight === 'number' ? cfg.strokeWeight : 3;
        var baseOpacity = typeof cfg.fillOpacity === 'number' ? cfg.fillOpacity : 0.42;
        var animateFill = cfg && cfg.animateFill === true;
        var zIndex = typeof cfg.zIndex === 'number' ? cfg.zIndex : 120;
        var durationMs = typeof cfg.durationMs === 'number' ? cfg.durationMs : 1200;
        var cycles = typeof cfg.cycles === 'number' ? cfg.cycles : 2;
        var startAt = Date.now();
        var totalMs = Math.max(300, durationMs * Math.max(1, cycles));
        var self = this;
        this._gridFocusAnimTimer = window.setInterval(function () {
            var elapsed = Date.now() - startAt;
            var phase = ((elapsed % durationMs) / durationMs);
            var energy = 0.5 - 0.5 * Math.cos(phase * 2 * Math.PI); // smooth breathe
            var strokeColor = self._mixHexColor(baseStroke, glowStroke, energy * 0.7);
            var strokeWeight = baseWeight + energy * 1.8;
            var fillOpacity = Math.min(0.86, baseOpacity + energy * 0.16);
            var pulseStyle = {
                strokeColor: strokeColor,
                strokeWeight: strokeWeight,
                zIndex: zIndex
            };
            if (animateFill) {
                pulseStyle.fillOpacity = fillOpacity;
            }
            polygon.setOptions(pulseStyle);
            if (elapsed >= totalMs) {
                self._stopGridFocusAnimation();
                var restoreStyle = {
                    strokeColor: baseStroke,
                    strokeWeight: baseWeight,
                    zIndex: zIndex
                };
                if (animateFill) {
                    restoreStyle.fillOpacity = baseOpacity;
                }
                polygon.setOptions(restoreStyle);
            }
        }, 130);
    };

    MapCore.prototype._resolveFeatureCenter = function (feature) {
        var geometry = feature && feature.geometry ? feature.geometry : null;
        if (!geometry || geometry.type !== 'Polygon') return null;
        var rings = geometry.coordinates || [];
        var path = this._normalizePathPoints(rings[0], 3);
        if (!Array.isArray(path) || path.length < 3) return null;
        var minLng = Infinity;
        var minLat = Infinity;
        var maxLng = -Infinity;
        var maxLat = -Infinity;
        for (var i = 0; i < path.length; i += 1) {
            var pt = path[i];
            if (!Array.isArray(pt) || pt.length < 2) continue;
            var lng = Number(pt[0]);
            var lat = Number(pt[1]);
            if (!Number.isFinite(lng) || !Number.isFinite(lat)) continue;
            if (lng < minLng) minLng = lng;
            if (lat < minLat) minLat = lat;
            if (lng > maxLng) maxLng = lng;
            if (lat > maxLat) maxLat = lat;
        }
        if (!Number.isFinite(minLng) || !Number.isFinite(minLat) || !Number.isFinite(maxLng) || !Number.isFinite(maxLat)) {
            return null;
        }
        return [(minLng + maxLng) / 2, (minLat + maxLat) / 2];
    };

    MapCore.prototype.focusGridCellById = function (h3Id, opts) {
        if (!h3Id) return false;
        var gridId = String(h3Id);
        var cfg = opts || {};
        var preserveFill = cfg.preserveFill !== false;
        var animateFill = cfg.animateFill === true;
        if (this.focusedGridOverlay && this.focusedGridOverlay.setMap) {
            this.focusedGridOverlay.setMap(null);
            this.focusedGridOverlay = null;
        }
        if (this.gridWebglEnabled && this.gridFeatureMap && this.gridFeatureMap[gridId]) {
            var feature = this.gridFeatureMap[gridId];
            var propsWebgl = (feature && feature.properties) || {};
            var rings = ((feature && feature.geometry) || {}).coordinates || [];
            var path = this._normalizePathPoints(rings[0], 3);
            if (!Array.isArray(path) || path.length < 3) return false;
            if (this.focusedGridPolygon) {
                this._restoreGridPolygonStyle(this.focusedGridPolygon);
                this.focusedGridPolygon = null;
            }
            var highlightStrokeWebgl = cfg.strokeColor || '#22d3ee';
            var highlightWeightWebgl = typeof cfg.strokeWeight === 'number' ? cfg.strokeWeight : 4;
            var baseFillOpacityWebgl = 0;
            if (!preserveFill || animateFill) {
                baseFillOpacityWebgl = typeof cfg.fillOpacity === 'number'
                    ? cfg.fillOpacity
                    : (typeof propsWebgl.fillOpacity === 'number' ? propsWebgl.fillOpacity : 0.08);
            }
            var highlightZWebgl = typeof cfg.zIndex === 'number' ? cfg.zIndex : 130;
            var overlay = new AMap.Polygon({
                path: path,
                strokeColor: highlightStrokeWebgl,
                strokeWeight: highlightWeightWebgl,
                strokeOpacity: 0.98,
                fillColor: propsWebgl.fillColor || '#42a5f5',
                fillOpacity: baseFillOpacityWebgl,
                zIndex: highlightZWebgl,
                clickable: false,
                bubble: true
            });
            overlay.__baseStyle = {
                strokeColor: highlightStrokeWebgl,
                strokeWeight: highlightWeightWebgl,
                fillColor: propsWebgl.fillColor || '#42a5f5',
                fillOpacity: baseFillOpacityWebgl,
                zIndex: highlightZWebgl
            };
            overlay.setMap(this.map);
            this.focusedGridOverlay = overlay;
            if (this.map && cfg.rememberView !== false) {
                var center0 = this.map.getCenter ? this.map.getCenter() : null;
                var zoom0 = this.map.getZoom ? this.map.getZoom() : null;
                if (center0 && center0.getLng && center0.getLat && typeof zoom0 === 'number') {
                    this._gridFocusViewBeforeLock = {
                        center: [center0.getLng(), center0.getLat()],
                        zoom: zoom0
                    };
                }
            }
            if (this.map) {
                if (cfg.fitView) {
                    this.map.setFitView([overlay]);
                    var zoomMin0 = typeof cfg.zoomMin === 'number' ? cfg.zoomMin : 16;
                    if (this.map.getZoom && this.map.setZoom) {
                        var currentZoom0 = this.map.getZoom();
                        if (currentZoom0 < zoomMin0) this.map.setZoom(zoomMin0);
                    }
                } else if (cfg.panTo !== false) {
                    var centerPoint = this._resolveFeatureCenter(feature);
                    if (centerPoint && this.map.setCenter) this.map.setCenter(centerPoint);
                }
            }
            if (cfg.animate !== false) {
                this._runGridFocusPulse(overlay, {
                    strokeColor: highlightStrokeWebgl,
                    strokeWeight: highlightWeightWebgl,
                    fillOpacity: baseFillOpacityWebgl,
                    animateFill: animateFill && !preserveFill,
                    zIndex: highlightZWebgl,
                    pulseColor: cfg.pulseColor || '#ecfeff'
                });
            } else {
                this._stopGridFocusAnimation();
            }
            return true;
        }
        if (!this.gridPolygonMap) return false;
        var polygon = this.gridPolygonMap[gridId];
        if (!polygon) return false;

        if (this.focusedGridPolygon && this.focusedGridPolygon !== polygon) {
            this._restoreGridPolygonStyle(this.focusedGridPolygon);
        }

        var highlightStroke = cfg.strokeColor || '#22d3ee';
        var highlightWeight = typeof cfg.strokeWeight === 'number' ? cfg.strokeWeight : 4;
        var baseFillOpacity = (polygon.__baseStyle && typeof polygon.__baseStyle.fillOpacity === 'number')
            ? polygon.__baseStyle.fillOpacity
            : 0.2;
        var highlightOpacity = baseFillOpacity;
        if (!preserveFill || animateFill) {
            highlightOpacity = typeof cfg.fillOpacity === 'number'
                ? cfg.fillOpacity
                : Math.min(0.72, Math.max(0.28, baseFillOpacity + 0.2));
        }
        var highlightZ = typeof cfg.zIndex === 'number' ? cfg.zIndex : 130;

        if (this.map && cfg.rememberView !== false) {
            var center = this.map.getCenter ? this.map.getCenter() : null;
            var zoom = this.map.getZoom ? this.map.getZoom() : null;
            if (center && center.getLng && center.getLat && typeof zoom === 'number') {
                this._gridFocusViewBeforeLock = {
                    center: [center.getLng(), center.getLat()],
                    zoom: zoom
                };
            }
        }

        polygon.setOptions({
            strokeColor: highlightStroke,
            strokeWeight: highlightWeight,
            fillOpacity: highlightOpacity,
            zIndex: highlightZ
        });
        this.focusedGridPolygon = polygon;

        if (this.map) {
            if (cfg.fitView) {
                // Fit only this polygon; avoid mixing in all overlays.
                this.map.setFitView([polygon]);
                var zoomMin = typeof cfg.zoomMin === 'number' ? cfg.zoomMin : 16;
                if (this.map.getZoom && this.map.setZoom) {
                    var currentZoom = this.map.getZoom();
                    if (currentZoom < zoomMin) this.map.setZoom(zoomMin);
                }
            } else if (cfg.panTo !== false && polygon.getBounds) {
                var bounds = polygon.getBounds();
                if (bounds && bounds.getCenter) {
                    this.map.panTo(bounds.getCenter());
                }
            }
        }
        if (cfg.animate !== false) {
            this._runGridFocusPulse(polygon, {
                strokeColor: highlightStroke,
                strokeWeight: highlightWeight,
                fillOpacity: highlightOpacity,
                animateFill: animateFill && !preserveFill,
                zIndex: highlightZ,
                pulseColor: cfg.pulseColor || '#ecfeff'
            });
        } else {
            this._stopGridFocusAnimation();
        }
        return true;
    };

    MapCore.prototype.clearGridFocus = function (opts) {
        var cfg = opts || {};
        this._stopGridFocusAnimation();
        if (this.focusedGridOverlay && this.focusedGridOverlay.setMap) {
            this.focusedGridOverlay.setMap(null);
        }
        this.focusedGridOverlay = null;
        if (this.focusedGridPolygon) {
            this._restoreGridPolygonStyle(this.focusedGridPolygon);
        }
        this.focusedGridPolygon = null;
        if (cfg.restoreView && this.map && this._gridFocusViewBeforeLock && Array.isArray(this._gridFocusViewBeforeLock.center)) {
            var restoreCenter = this._gridFocusViewBeforeLock.center;
            var restoreZoom = this._gridFocusViewBeforeLock.zoom;
            if (this.map.setZoomAndCenter && typeof restoreZoom === 'number') {
                this.map.setZoomAndCenter(restoreZoom, restoreCenter);
            } else {
                if (this.map.setCenter) this.map.setCenter(restoreCenter);
                if (this.map.setZoom && typeof restoreZoom === 'number') this.map.setZoom(restoreZoom);
            }
        }
        this._gridFocusViewBeforeLock = null;
    };

    MapCore.prototype.drawCityBoundary = function (cityCodeOrName) {
        var self = this;
        if (this.mapMode !== 'city' || !cityCodeOrName) return;
        this.clearBoundaryPolygons();

        AMap.plugin('AMap.DistrictSearch', function () {
            var ds = new AMap.DistrictSearch({
                level: 'city',
                extensions: 'all',
                subdistrict: 0
            });

            ds.search(cityCodeOrName, function (status, result) {
                if (status !== 'complete') return;
                var list = result.districtList || [];
                if (!list.length) return;

                var boundaries = list[0].boundaries || [];
                boundaries.forEach(function (path) {
                    var polygon = new AMap.Polygon({
                        path: path,
                        strokeColor: '#00bcd4',
                        strokeWeight: 2,
                        strokeOpacity: 0.9,
                        fillColor: '#00bcd4',
                        fillOpacity: 0
                    });
                    polygon.setMap(self.map);
                    self.boundaryPolygons.push(polygon);
                });

                self.updateFitView();
            });
        });
    };

    MapCore.prototype.updateFitView = function (overlays) {
        if (!this.map) return;
        var objects = overlays ? overlays.slice() : [];
        var isOverlayVisibleOnMap = function (overlay) {
            if (!overlay) return false;
            if (typeof overlay.getMap === 'function') {
                try {
                    return !!overlay.getMap();
                } catch (_) {
                    return false;
                }
            }
            return true;
        };
        objects = objects.filter(function (overlay) {
            return isOverlayVisibleOnMap(overlay);
        });

        if (isOverlayVisibleOnMap(this.mainCircle)) {
            objects.push(this.mainCircle);
        }
        if (this.mapMode === 'city') {
            this.cityCircles.forEach(function (circle) {
                if (isOverlayVisibleOnMap(circle)) {
                    objects.push(circle);
                }
            });
        }
        this.boundaryPolygons.forEach(function (polygon) {
            if (isOverlayVisibleOnMap(polygon)) {
                objects.push(polygon);
            }
        });
        this.customPolygons.forEach(function (polygon) {
            if (isOverlayVisibleOnMap(polygon)) {
                objects.push(polygon);
            }
        });
        this.gridPolygons.forEach(function (polygon) {
            if (isOverlayVisibleOnMap(polygon)) {
                objects.push(polygon);
            }
        });

        if (objects.length) {
            this.map.setFitView(objects);
        } else {
            this.map.setFitView();
        }
    };

export { MapCore };
