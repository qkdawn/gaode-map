import { asText, cloneArray, cloneObject } from './normalizers.js'
import {
  capturePptMapRequestAsset,
  isPptMapSnapshotRequest,
} from '../ppt-planning/map-snapshot.js'
import {
  capturePptCarrierSnapshotAsset,
  isPptCarrierSnapshotRequest,
} from '../ppt-planning/carrier-snapshot.js'

function defaultFailedVisual(visual = {}, error = null) {
  return {
    ...cloneObject(visual),
    data: {
      ...cloneObject(visual.data),
      capture_error: {
        code: asText(error && error.message ? error.message : error) || 'ppt_map_snapshot_capture_failed',
        message: asText(error && error.message ? error.message : error) || '地图截图失败',
        captured_at: new Date().toISOString(),
      },
    },
  }
}

export function createAgentPptVisualSnapshotMethods() {
  return {
    stableAgentPptMapSnapshotJson(value = null) {
      if (Array.isArray(value)) {
        return `[${value.map((item) => this.stableAgentPptMapSnapshotJson(item)).join(',')}]`
      }
      if (value && typeof value === 'object') {
        return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${this.stableAgentPptMapSnapshotJson(value[key])}`).join(',')}}`
      }
      return JSON.stringify(value ?? null)
    },
    buildAgentPptMapSnapshotSceneKey(mapRequest = {}, visual = {}) {
      const request = cloneObject(mapRequest)
      const layers = cloneArray(request.layers)
        .map((layer) => {
          const item = cloneObject(layer)
          return {
            layer_type: asText(item.layer_type || item.layerType || item.type),
            source: asText(item.source || item.source_id || item.sourceId),
            role: asText(item.role),
            metric: asText(item.metric || item.metric_key || item.metricKey),
          }
        })
        .filter((layer) => layer.layer_type || layer.source)
        .sort((a, b) => this.stableAgentPptMapSnapshotJson(a).localeCompare(this.stableAgentPptMapSnapshotJson(b)))
      const scope = cloneObject(request.scope || request.focus || request.bounds)
      const sourceIds = cloneArray(visual.source_ids || visual.sourceIds || request.source_ids || request.sourceIds)
        .map((item) => asText(item))
        .filter(Boolean)
        .sort()
      const fingerprint = asText(
        typeof this.buildAgentVisualSnapshotFingerprint === 'function'
          ? this.buildAgentVisualSnapshotFingerprint()
          : '',
      ) || asText(
        (typeof this.getCurrentAgentHistoryId === 'function' && this.getCurrentAgentHistoryId())
        || this.currentHistoryRecordId
        || this.currentAnalysisId
        || this.analysisId,
      )
      return this.stableAgentPptMapSnapshotJson({
        version: 'ppt-map-scene-v1',
        fingerprint,
        composition: asText(request.composition),
        history_id: asText(request.history_id || request.historyId || request.area_id || request.areaId || scope.history_id || scope.historyId || scope.area_id || scope.areaId),
        scope,
        metric: asText(request.metric || request.metric_key || request.metricKey),
        basemap: cloneObject(request.basemap),
        layers,
        source_ids: sourceIds,
      })
    },
    getCachedAgentPptMapSnapshotAsset(sceneKey = '') {
      const cache = this.pptMapSnapshotAssetCache && typeof this.pptMapSnapshotAssetCache === 'object'
        ? this.pptMapSnapshotAssetCache
        : {}
      const asset = cloneObject(cache[asText(sceneKey)])
      return asText(asset.data_url || asset.dataUrl).startsWith('data:image/') ? asset : null
    },
    setCachedAgentPptMapSnapshotAsset(sceneKey = '', asset = {}) {
      const key = asText(sceneKey)
      const dataUrl = asText(asset && (asset.data_url || asset.dataUrl))
      if (!key || !dataUrl.startsWith('data:image/')) return null
      const cached = cloneObject(asset)
      this.pptMapSnapshotAssetCache = {
        ...(this.pptMapSnapshotAssetCache && typeof this.pptMapSnapshotAssetCache === 'object' ? this.pptMapSnapshotAssetCache : {}),
        [key]: cached,
      }
      return cached
    },
    cloneAgentPptMapSnapshotAssetForVisual(asset = {}, visual = {}) {
      return {
        ...cloneObject(asset),
        visual_id: asText(visual.visual_id || visual.visualId),
      }
    },
    async captureAgentPptMapRequestSceneAsset(mapRequest = {}, visual = {}, sceneKey = '', options = {}) {
      const cached = this.getCachedAgentPptMapSnapshotAsset(sceneKey)
      if (cached) return cached
      if (typeof this.ensurePptMapRequestHistoryData === 'function') {
        await this.ensurePptMapRequestHistoryData(mapRequest)
      }
      let asset = null
      let offscreenError = null
      const preferOffscreen = !!options.preferOffscreenMapCapture
      try {
        if (!preferOffscreen && typeof this.renderPptMapRequestMainMapSnapshot === 'function') {
          asset = await capturePptMapRequestAsset(mapRequest, {
            renderMapRequest: (request, renderOptions) => this.renderPptMapRequestMainMapSnapshot(request, renderOptions),
            requireRenderer: true,
          })
        } else if (preferOffscreen && typeof this.ensurePptMapSnapshotRendererReady === 'function') {
          await this.ensurePptMapSnapshotRendererReady()
          asset = await capturePptMapRequestAsset(mapRequest, {
            renderMapRequest: typeof this.renderPptMapRequestSnapshot === 'function'
              ? (request, renderOptions) => this.renderPptMapRequestSnapshot(request, renderOptions)
              : undefined,
            requireRenderer: true,
            html2canvas: typeof globalThis !== 'undefined' && typeof globalThis.html2canvas === 'function'
              ? globalThis.html2canvas
              : (typeof window !== 'undefined' && typeof window.html2canvas === 'function' ? window.html2canvas : undefined),
          })
        } else {
          throw new Error('ppt_map_main_capture_unavailable')
        }
      } catch (error) {
        if (!preferOffscreen || !options.allowMainMapCapture) {
          throw error
        }
        offscreenError = error
        if (typeof console !== 'undefined' && console.warn) {
          console.warn('PPT offscreen map snapshot request capture failed; trying explicit main map fallback', asText(visual.visual_id || visual.visualId), error)
        }
      }
      if (!asset && preferOffscreen && options.allowMainMapCapture && typeof this.renderPptMapRequestMainMapSnapshot === 'function') {
        try {
          asset = await capturePptMapRequestAsset(mapRequest, {
            renderMapRequest: (request, fallbackOptions) => this.renderPptMapRequestMainMapSnapshot(request, fallbackOptions),
            requireRenderer: true,
          })
        } catch (error) {
          if (offscreenError) {
            throw Object.assign(new Error('ppt_map_main_capture_failed'), {
              cause: error,
              detail: `${asText(offscreenError && offscreenError.message ? offscreenError.message : offscreenError)}; ${asText(error && error.message ? error.message : error)}`,
            })
          }
          throw error
        }
      }
      if (!asset) throw new Error('ppt_map_snapshot_capture_failed')
      return this.setCachedAgentPptMapSnapshotAsset(sceneKey, asset) || asset
    },
    async captureAgentPptMapRequestAssets(visualSpecs = [], options = {}) {
      const assets = []
      const nextVisualSpecs = []
      const mapGroups = new Map()
      for (const visual of cloneArray(visualSpecs)) {
        if (!isPptMapSnapshotRequest(visual)) continue
        const data = cloneObject(visual.data)
        const mapRequest = cloneObject(data.map_request || data.mapRequest)
        const sceneKey = this.buildAgentPptMapSnapshotSceneKey(mapRequest, visual)
        if (!mapGroups.has(sceneKey)) {
          mapGroups.set(sceneKey, { sceneKey, mapRequest, visuals: [] })
        }
        mapGroups.get(sceneKey).visuals.push(cloneObject(visual))
      }

      for (const group of mapGroups.values()) {
        try {
          const asset = await this.captureAgentPptMapRequestSceneAsset(group.mapRequest, group.visuals[0], group.sceneKey, options)
          group.visuals.forEach((visual) => {
            assets.push(this.cloneAgentPptMapSnapshotAssetForVisual(asset, visual))
            nextVisualSpecs.push(cloneObject(visual))
          })
        } catch (error) {
          group.visuals.forEach((visual) => {
            const failedVisual = typeof this.attachPptMapSnapshotCaptureError === 'function'
              ? this.attachPptMapSnapshotCaptureError(visual, error)
              : defaultFailedVisual(visual, error)
            nextVisualSpecs.push(failedVisual)
            if (typeof console !== 'undefined' && console.warn) {
              console.warn('PPT map snapshot request capture failed for visual', asText(visual.visual_id || visual.visualId), error)
            }
          })
        }
      }

      for (const visual of cloneArray(visualSpecs)) {
        if (!isPptCarrierSnapshotRequest(visual)) continue
        try {
          const data = cloneObject(visual.data)
          const carrierRequest = {
            ...cloneObject(data.carrier_snapshot_request || data.carrierSnapshotRequest),
            package_source_id: asText(data.package_source_id || data.packageSourceId || cloneObject(data.carrier_snapshot_request || data.carrierSnapshotRequest).package_source_id || cloneObject(data.carrier_snapshot_request || data.carrierSnapshotRequest).packageSourceId),
            title: asText(data.title) || asText(visual.title),
          }
          const state = typeof this.getAgentPptPlanningStateWithSystemSources === 'function'
            ? this.getAgentPptPlanningStateWithSystemSources()
            : {}
          const asset = await capturePptCarrierSnapshotAsset(carrierRequest, {
            sources: cloneArray(state.sources),
          })
          assets.push({
            ...asset,
            visual_id: asText(visual.visual_id || visual.visualId),
          })
          nextVisualSpecs.push(cloneObject(visual))
        } catch (error) {
          const failedVisual = typeof this.attachPptMapSnapshotCaptureError === 'function'
            ? this.attachPptMapSnapshotCaptureError(visual, error)
            : defaultFailedVisual(visual, error)
          nextVisualSpecs.push(failedVisual)
          if (typeof console !== 'undefined' && console.warn) {
            console.warn('PPT map snapshot request capture failed for visual', asText(visual.visual_id || visual.visualId), error)
          }
        }
      }
      return { assets, visualSpecs: nextVisualSpecs }
    },
  }
}
