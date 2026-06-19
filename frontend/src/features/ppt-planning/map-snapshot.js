import { asText, cloneArray, cloneObject } from '../agent/normalizers.js'

const ALLOWED_LAYER_TYPES = new Set([
  'scope_boundary',
  'poi_points',
  'h3_grid',
  'population_grid',
  'nightlight_grid',
  'road_syntax',
])

function layerType(layer = {}) {
  return asText(layer.layer_type || layer.layerType || layer.type)
}

function createLayerNode(className = '', label = '') {
  const node = document.createElement('div')
  node.className = className
  node.textContent = label
  return node
}

function defaultLayerRenderer(className, label) {
  return ({ host }) => {
    host.appendChild(createLayerNode(className, label))
  }
}

export const MAP_LAYER_RENDERERS = Object.freeze({
  scope_boundary: defaultLayerRenderer('ppt-map-layer ppt-map-layer-scope', ''),
  poi_points: defaultLayerRenderer('ppt-map-layer ppt-map-layer-poi', ''),
  h3_grid: defaultLayerRenderer('ppt-map-layer ppt-map-layer-h3', ''),
  population_grid: defaultLayerRenderer('ppt-map-layer ppt-map-layer-population', ''),
  nightlight_grid: defaultLayerRenderer('ppt-map-layer ppt-map-layer-nightlight', ''),
  road_syntax: defaultLayerRenderer('ppt-map-layer ppt-map-layer-road', ''),
})

export function isPptMapSnapshotRequest(visual = {}) {
  const data = cloneObject(visual.data)
  return asText(visual.visual_type || visual.visualType) === 'existing_asset'
    && asText(visual.status) === 'needs_existing_asset'
    && asText(data.composition || data.composition_type || data.compositionType) === 'map_snapshot_request'
    && !!(data.map_request || data.mapRequest)
}

function normalizeMapRequest(mapRequest = {}) {
  const request = cloneObject(mapRequest)
  const composition = asText(request.composition)
  const layers = cloneArray(request.layers)
    .map((layer) => cloneObject(layer))
    .filter((layer) => ALLOWED_LAYER_TYPES.has(layerType(layer)))
    .slice(0, 4)
  return {
    ...request,
    composition,
    layers,
    annotations: cloneArray(request.annotations).map((item) => cloneObject(item)).slice(0, 8),
  }
}

function validateMapRequest(mapRequest = {}) {
  const request = normalizeMapRequest(mapRequest)
  if (!request.composition) throw new Error('ppt_map_request_missing_composition')
  if (request.composition !== 'overview' && !request.layers.some((layer) => layerType(layer) !== 'scope_boundary')) {
    throw new Error('ppt_map_request_missing_renderable_layer')
  }
  return request
}

function isPptImageDataUrl(value = '') {
  return /^data:image\/[a-z0-9.+-]+;base64,/i.test(asText(value))
}

function injectSnapshotStyles(host) {
  const style = document.createElement('style')
  style.textContent = `
    .ppt-map-snapshot-host{position:fixed;left:-10000px;top:0;width:960px;height:540px;overflow:hidden;background:#f8fafc;color:#0f172a;font-family:Arial,sans-serif}
    .ppt-map-snapshot-stage{position:relative;width:100%;height:100%;background:#eef2f7}
    .ppt-map-snapshot-stage.is-dark{background:#111827}
    .ppt-map-layer{position:absolute;inset:38px;border-radius:18px;box-sizing:border-box}
    .ppt-map-layer-scope{border:3px solid rgba(15,23,42,.58);background:rgba(255,255,255,.08)}
    .ppt-map-layer-h3{background:repeating-linear-gradient(90deg,rgba(37,99,235,.24) 0 18px,rgba(255,255,255,.12) 18px 36px),repeating-linear-gradient(0deg,rgba(37,99,235,.16) 0 18px,transparent 18px 36px)}
    .ppt-map-layer-population{background:radial-gradient(circle at 45% 48%,rgba(220,38,38,.54),rgba(245,158,11,.32) 32%,rgba(37,99,235,.18) 62%,transparent 76%)}
    .ppt-map-layer-nightlight{background:radial-gradient(circle at 48% 44%,rgba(251,191,36,.72),rgba(245,158,11,.34) 25%,rgba(30,64,175,.24) 55%,transparent 78%)}
    .ppt-map-layer-poi{background:radial-gradient(circle at 30% 40%,#ef4444 0 4px,transparent 5px),radial-gradient(circle at 62% 54%,#ef4444 0 4px,transparent 5px),radial-gradient(circle at 50% 30%,#ef4444 0 4px,transparent 5px),radial-gradient(circle at 72% 38%,#ef4444 0 4px,transparent 5px)}
    .ppt-map-layer-road{background:linear-gradient(28deg,transparent 44%,rgba(15,23,42,.58) 45%,rgba(15,23,42,.58) 46%,transparent 47%),linear-gradient(145deg,transparent 38%,rgba(37,99,235,.58) 39%,rgba(37,99,235,.58) 41%,transparent 42%),linear-gradient(90deg,transparent 50%,rgba(15,23,42,.45) 51%,rgba(15,23,42,.45) 52%,transparent 53%)}
    .ppt-map-snapshot-title{position:absolute;left:30px;top:24px;font-size:22px;font-weight:700}
    .ppt-map-snapshot-annotations{position:absolute;left:30px;right:30px;bottom:24px;display:flex;gap:10px;flex-wrap:wrap}
    .ppt-map-snapshot-annotations span{background:rgba(255,255,255,.9);border:1px solid rgba(148,163,184,.42);border-radius:6px;padding:7px 10px;font-size:13px;font-weight:700}
  `
  host.appendChild(style)
}

async function renderDomSnapshot(mapRequest, options = {}) {
  if (typeof document === 'undefined') throw new Error('document_unavailable')
  if (typeof html2canvas !== 'function' && typeof options.html2canvas !== 'function') {
    throw new Error('html2canvas_unavailable')
  }
  const capture = typeof options.html2canvas === 'function' ? options.html2canvas : html2canvas
  const host = document.createElement('div')
  host.className = 'ppt-map-snapshot-host'
  const stage = document.createElement('div')
  stage.className = `ppt-map-snapshot-stage ${asText(mapRequest.basemap && mapRequest.basemap.style) === 'dark' ? 'is-dark' : ''}`
  host.appendChild(stage)
  injectSnapshotStyles(host)
  document.body.appendChild(host)
  try {
    const title = createLayerNode('ppt-map-snapshot-title', asText(mapRequest.title) || '空间诊断图')
    stage.appendChild(title)
    for (const layer of mapRequest.layers) {
      const renderer = MAP_LAYER_RENDERERS[layerType(layer)]
      if (typeof renderer !== 'function') throw new Error(`ppt_map_layer_renderer_missing:${layerType(layer)}`)
      renderer({ host: stage, layer, mapRequest })
    }
    const annotationHost = document.createElement('div')
    annotationHost.className = 'ppt-map-snapshot-annotations'
    cloneArray(mapRequest.annotations).slice(0, 4).forEach((annotation) => {
      const label = asText(annotation.label)
      if (!label) return
      const value = annotation.value === null || annotation.value === undefined ? '' : String(annotation.value)
      annotationHost.appendChild(createLayerNode('', `${label}${value ? ` ${value}${asText(annotation.unit)}` : ''}`))
    })
    stage.appendChild(annotationHost)
    const canvas = await capture(host, { useCORS: true, backgroundColor: null, scale: 1, logging: false })
    const dataUrl = canvas && typeof canvas.toDataURL === 'function' ? canvas.toDataURL('image/png') : ''
    if (!isPptImageDataUrl(dataUrl)) throw new Error('ppt_map_asset_invalid_data_url')
    return dataUrl
  } finally {
    if (host.parentNode) host.parentNode.removeChild(host)
  }
}

export async function capturePptMapRequestAsset(mapRequest = {}, options = {}) {
  const request = validateMapRequest(mapRequest)
  if (options.requireRenderer && typeof options.renderMapRequest !== 'function') {
    throw new Error('ppt_map_request_renderer_unavailable')
  }
  const render = typeof options.renderMapRequest === 'function' ? options.renderMapRequest : renderDomSnapshot
  const dataUrl = await render(request, options)
  if (!isPptImageDataUrl(dataUrl)) {
    throw new Error('ppt_map_asset_invalid_data_url')
  }
  const digest = `${request.composition}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
  return {
    asset_id: `ppt-map-snapshot-${digest}`,
    asset_kind: 'map_snapshot',
    kind: 'map_snapshot',
    source: 'frontend_map_snapshot_request',
    title: asText(request.title) || 'PPT 地图截图',
    data_url: dataUrl,
    status: 'ready',
    captured_at: new Date().toISOString(),
    data: {
      composition: 'map_snapshot',
      map_request: request,
    },
  }
}
