import { markRaw } from 'vue'
import { MapCore } from '../../../map/core'

function createAnalysisMapOrchestratorMethods() {
  return {
    attachAmapRuntimeErrorProbe() {
      if (this.amapRuntimeErrorListener || this.amapRuntimeRejectionListener) return
      const buildPayload = (base = {}) => {
        const manager = this.markerManager
        const clustererCount = manager && manager.typeClusterers && typeof manager.typeClusterers === 'object'
          ? Object.keys(manager.typeClusterers).length
          : 0
        const markerCount = manager && Array.isArray(manager.markers) ? manager.markers.length : 0
        return Object.assign({
          step: Number(this.step || 0),
          panel: String(this.activeStep3Panel || ''),
          poi_suspended_for_syntax: !!this.poiSystemSuspendedForSyntax,
          marker_manager_alive: !!manager,
          marker_count: markerCount,
          clusterer_count: clustererCount,
          road_active_layer: String(this.roadSyntaxActiveLayerKey || ''),
          road_switch_in_progress: !!this.roadSyntaxSwitchInProgress,
          road_pool_ready: !!this.roadSyntaxPoolReady,
          road_map_write_queue_pending: Number(this.roadSyntaxMapWriteQueuePending || 0),
        }, base || {})
      }
      const matchRuntimeMessage = (message = '', filename = '') => {
        const msg = String(message || '')
        const file = String(filename || '')
        return (
          file.indexOf('maps?v=') >= 0
          || msg.indexOf('split') >= 0
          || msg.indexOf('Ud') >= 0
          || msg.indexOf('Pixel(NaN') >= 0
        )
      }
      this.amapRuntimeErrorListener = (event) => {
        const message = event && event.message ? String(event.message) : ''
        const filename = event && event.filename ? String(event.filename) : ''
        if (!matchRuntimeMessage(message, filename)) return
        console.error('[diag] amap runtime error', buildPayload({
          message,
          filename,
          lineno: Number((event && event.lineno) || 0),
          colno: Number((event && event.colno) || 0),
        }))
      }
      this.amapRuntimeRejectionListener = (event) => {
        const reason = event ? (event.reason || '') : ''
        const text = reason && reason.message ? String(reason.message) : String(reason || '')
        if (!matchRuntimeMessage(text, '')) return
        console.error('[diag] amap runtime rejection', buildPayload({
          reason: text,
        }))
      }
      window.addEventListener('error', this.amapRuntimeErrorListener)
      window.addEventListener('unhandledrejection', this.amapRuntimeRejectionListener)
    },
    detachAmapRuntimeErrorProbe() {
      if (this.amapRuntimeErrorListener) {
        window.removeEventListener('error', this.amapRuntimeErrorListener)
      }
      if (this.amapRuntimeRejectionListener) {
        window.removeEventListener('unhandledrejection', this.amapRuntimeRejectionListener)
      }
      this.amapRuntimeErrorListener = null
      this.amapRuntimeRejectionListener = null
    },
    async onBasemapSourceChange() {
      const allowedSources = ['amap', 'osm', 'tianditu']
      let source = allowedSources.includes(this.basemapSource) ? this.basemapSource : 'amap'
      if (source === 'tianditu') {
        const tileReady = await this.validateTiandituSource()
        if (!tileReady) {
          this.tdtDiagCopyStatus = ''
        }
      } else {
        this.tdtDiag = null
        this.tdtDiagCopyStatus = ''
        if (this.errorMessage && this.errorMessage.indexOf('天地图') >= 0) {
          this.errorMessage = ''
        }
      }
      this.basemapSource = source
      if (this.mapCore && this.mapCore.setBasemapSource) {
        const applyResult = this.mapCore.setBasemapSource(source)
        if (source === 'tianditu' && applyResult && applyResult.ok === false) {
          this.tdtDiag = {
            ok: false,
            phase: 'map-init',
            status: null,
            contentType: '',
            bodySnippet: applyResult.message || '',
            reason: applyResult.code || 'wmts-layer-init-failed',
          }
          this.errorMessage = '天地图 WMTS 图层初始化失败，请检查：Key 类型=Web JS，白名单包含 localhost/127.0.0.1（及端口）。'
        } else if (source === 'tianditu' && applyResult && applyResult.ok === true) {
          if (this.errorMessage && this.errorMessage.indexOf('天地图') >= 0) {
            this.errorMessage = ''
          }
        }
      }
      this.applySimplifyConfig()
    },
    _toNumber(value, fallback = 0) {
      const n = Number(value)
      return Number.isFinite(n) ? n : fallback
    },
    loadAMapScript(key, securityCode) {
      return new Promise((resolve, reject) => {
        if (window.AMap && window.AMap.Map) {
          resolve()
          return
        }
        window._AMapSecurityConfig = { securityJsCode: securityCode }
        const script = document.createElement('script')
        script.src = `https://webapi.amap.com/maps?v=1.4.15&key=${key}`
        script.onload = resolve
        script.onerror = reject
        document.head.appendChild(script)
      })
    },
    async probeTiandituTile(timeoutMs = 4500) {
      const key = (this.config && this.config.tianditu_key ? String(this.config.tianditu_key) : '').trim()
      if (!key) {
        return {
          ok: false,
          phase: 'wmts-probe',
          status: null,
          contentType: '',
          bodySnippet: '',
          reason: 'missing-key',
          url: '',
        }
      }
      const probeUrl = `https://t0.tianditu.gov.cn/vec_w/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=vec&STYLE=default&TILEMATRIXSET=w&FORMAT=tiles&TILEMATRIX=7&TILEROW=53&TILECOL=107&tk=${encodeURIComponent(key)}&_ts=${Date.now()}`
      const controller = new AbortController()
      const timer = window.setTimeout(() => controller.abort(), timeoutMs)
      try {
        const response = await fetch(probeUrl, {
          method: 'GET',
          cache: 'no-store',
          signal: controller.signal,
        })
        const contentType = String(response.headers.get('content-type') || '').toLowerCase()
        const isImage = this.isImageContentType(contentType)
        let bodySnippet = ''
        if (!isImage) {
          try {
            bodySnippet = this._trimText(await response.text(), 300)
          } catch (_) {
            bodySnippet = ''
          }
        }
        const status = response.status
        const ok = response.ok && isImage
        let reason = 'ok'
        if (!ok) {
          if (status === 418) reason = 'http-418'
          else if (status >= 500) reason = 'http-5xx'
          else if (status >= 400) reason = 'http-4xx'
          else if (response.ok) reason = 'non-image-response'
          else reason = 'http-error'
        }
        return {
          ok: ok,
          phase: 'wmts-probe',
          status: status,
          contentType: contentType,
          bodySnippet: bodySnippet,
          reason: reason,
          url: probeUrl,
        }
      } catch (e) {
        if (e && e.name === 'AbortError') {
          return {
            ok: false,
            phase: 'wmts-probe',
            status: null,
            contentType: '',
            bodySnippet: '',
            reason: 'timeout',
            url: probeUrl,
          }
        }
        return {
          ok: false,
          phase: 'wmts-probe',
          status: null,
          contentType: '',
          bodySnippet: this._trimText(e && e.message ? e.message : String(e), 300),
          reason: 'network-error',
          url: probeUrl,
        }
      } finally {
        window.clearTimeout(timer)
      }
    },
    async validateTiandituSource() {
      const result = await this.probeTiandituTile()
      this.tdtDiag = result
      this.tdtDiagCopyStatus = ''
      if (result.ok) {
        if (this.errorMessage && this.errorMessage.indexOf('天地图') >= 0) {
          this.errorMessage = ''
        }
        return true
      }
      if (result.reason === 'missing-key') {
        this.errorMessage = '未配置天地图 Key（TIANDITU_KEY）。'
      } else if (result.reason === 'timeout') {
        this.errorMessage = '天地图 WMTS 探测超时，请稍后重试（配置修改可能需要 5-10 分钟生效）。'
      } else if (result.reason === 'http-418') {
        this.errorMessage = '天地图 WMTS 探测被拦截（HTTP 418），请检查 Key 类型=Web JS，白名单包含 localhost/127.0.0.1（及端口）。'
      } else {
        this.errorMessage = `天地图 WMTS 探测失败（${result.status || 'NO_STATUS'}），请检查 Key 与白名单。`
      }
      return false
    },
    isImageContentType(contentType) {
      const ct = String(contentType || '').toLowerCase()
      return ct.indexOf('image/') >= 0 || ct.indexOf('application/octet-stream') >= 0
    },
    _trimText(value, maxLen = 300) {
      const text = String(value || '')
      if (text.length <= maxLen) return text
      return text.slice(0, maxLen) + '...'
    },
    buildTdtDiagText() {
      if (!this.tdtDiag) return ''
      const rows = [
        `ok=${this.tdtDiag.ok}`,
        `phase=${this.tdtDiag.phase || '-'}`,
        `reason=${this.tdtDiag.reason || '-'}`,
        `status=${this.tdtDiag.status === null || this.tdtDiag.status === undefined ? '-' : this.tdtDiag.status}`,
        `contentType=${this.tdtDiag.contentType || '-'}`,
      ]
      if (this.tdtDiag.url) rows.push(`url=${this.tdtDiag.url}`)
      if (this.tdtDiag.bodySnippet) rows.push(`body=${this.tdtDiag.bodySnippet}`)
      return rows.join('\n')
    },
    async copyTdtDiag() {
      const text = this.buildTdtDiagText()
      if (!text) {
        this.tdtDiagCopyStatus = '无可复制内容'
        return
      }
      try {
        await navigator.clipboard.writeText(text)
        this.tdtDiagCopyStatus = '已复制'
      } catch (e) {
        console.error(e)
        this.tdtDiagCopyStatus = '复制失败，请手动复制'
      }
    },
    roadSyntaxAttachMapListeners() {
      const map = this.mapCore && this.mapCore.map ? this.mapCore.map : null
      if (!map) return
      this.roadSyntaxDetachMapListeners()
      this.roadSyntaxZoomStartListener = () => {
        this.roadSyntaxMapInteracting = true
        if (this.isRoadSyntaxMetricViewActive()) {
          this.roadSyntaxEnterLowFidelityMode()
        }
      }
      this.roadSyntaxMoveStartListener = () => {
        this.roadSyntaxMapInteracting = true
        if (this.isRoadSyntaxMetricViewActive()) {
          this.roadSyntaxEnterLowFidelityMode()
        }
      }
      this.roadSyntaxMoveEndListener = () => {
        this.roadSyntaxMapInteracting = false
        if (this.isRoadSyntaxMetricViewActive()) {
          this.scheduleRoadSyntaxViewportRefresh('moveend')
          this.roadSyntaxLogOverlayHealth('moveend')
        }
        if (this.markerManager && typeof this.markerManager.logCoordinateHealth === 'function') {
          this.markerManager.logCoordinateHealth('road-syntax:moveend')
        }
      }
      this.roadSyntaxZoomListener = () => {
        this.roadSyntaxMapInteracting = false
        if (this.isRoadSyntaxMetricViewActive()) {
          this.scheduleRoadSyntaxViewportRefresh('zoomend')
          this.roadSyntaxLogOverlayHealth('zoomend')
        }
        if (this.markerManager && typeof this.markerManager.logCoordinateHealth === 'function') {
          this.markerManager.logCoordinateHealth('road-syntax:zoomend')
        }
      }
      map.on('zoomstart', this.roadSyntaxZoomStartListener)
      map.on('movestart', this.roadSyntaxMoveStartListener)
      map.on('moveend', this.roadSyntaxMoveEndListener)
      map.on('zoomend', this.roadSyntaxZoomListener)
    },
    roadSyntaxDetachMapListeners() {
      const map = this.mapCore && this.mapCore.map ? this.mapCore.map : null
      if (map && this.roadSyntaxZoomListener) {
        try { map.off('zoomend', this.roadSyntaxZoomListener) } catch (_) { }
      }
      if (map && this.roadSyntaxZoomStartListener) {
        try { map.off('zoomstart', this.roadSyntaxZoomStartListener) } catch (_) { }
      }
      if (map && this.roadSyntaxMoveStartListener) {
        try { map.off('movestart', this.roadSyntaxMoveStartListener) } catch (_) { }
      }
      if (map && this.roadSyntaxMoveEndListener) {
        try { map.off('moveend', this.roadSyntaxMoveEndListener) } catch (_) { }
      }
      this.roadSyntaxZoomListener = null
      this.roadSyntaxZoomStartListener = null
      this.roadSyntaxMoveStartListener = null
      this.roadSyntaxMoveEndListener = null
    },
    initMap() {
      const mapCore = new MapCore('container', {
        center: { lng: 112.9388, lat: 28.2282 },
        zoom: 13,
        zooms: [3, 20],
        mapData: {},
        basemapSource: this.basemapSource,
        basemapMuted: false,
        tiandituKey: this.config ? this.config.tianditu_key : '',
        tiandituContainerId: 'tianditu-container',
        onGridFeatureClick: (payload) => this.onH3GridFeatureClick(payload),
      })
      mapCore.initMap()
      this.mapCore = markRaw(mapCore)
      this.applySimplifyConfig()
      if (this.basemapSource === 'tianditu' && mapCore.lastBasemapError) {
        this.tdtDiag = {
          ok: false,
          phase: 'map-init',
          status: null,
          contentType: '',
          bodySnippet: mapCore.lastBasemapError.message || '',
          reason: mapCore.lastBasemapError.code || 'wmts-layer-init-failed',
        }
        this.errorMessage = '天地图 WMTS 图层初始化失败，请检查：Key 类型=Web JS，白名单包含 localhost/127.0.0.1（及端口）。'
      }

      mapCore.map.on('click', (e) => {
        if (this.sidebarView !== 'wizard' || this.step !== 1) return
        if (this.isochroneScopeMode !== 'point') return
        if (this.drawScopeActive) return
        this.setSelectedPoint(e.lnglat)
      })
      this.roadSyntaxAttachMapListeners()
    },
    resizeAnalysisMap() {
      const map = this.mapCore && this.mapCore.map
      if (!map || typeof map.resize !== 'function') return
      const resize = () => {
        if (this.mapCore && this.mapCore.map === map) map.resize()
      }
      if (typeof window !== 'undefined' && typeof window.requestAnimationFrame === 'function') {
        window.requestAnimationFrame(() => window.requestAnimationFrame(resize))
      } else {
        window.setTimeout(resize, 0)
      }
    },
  }
}

export { createAnalysisMapOrchestratorMethods }
