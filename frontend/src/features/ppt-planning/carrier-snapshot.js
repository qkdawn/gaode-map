import { asText, cloneArray, cloneObject } from '../agent/normalizers.js'
import { buildPptCarrierPreviewModel } from './carrier-preview.js'

const CARRIER_PACKAGE_PREFIX = 'package:poi-road-carriers:'

function isImageDataUrl(value = '') {
  return /^data:image\/[a-z0-9.+-]+;base64,/i.test(asText(value))
}

function escapeXml(value = '') {
  return asText(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function encodeBase64Utf8(value = '') {
  if (typeof btoa === 'function') {
    return btoa(unescape(encodeURIComponent(value)))
  }
  if (typeof Buffer !== 'undefined') {
    return Buffer.from(value, 'utf8').toString('base64')
  }
  throw new Error('ppt_carrier_snapshot_encoder_unavailable')
}

function carrierPackageSourceIdFromVisual(visual = {}) {
  const data = cloneObject(visual.data)
  const request = cloneObject(data.carrier_snapshot_request || data.carrierSnapshotRequest)
  const explicit = asText(data.package_source_id || data.packageSourceId || request.package_source_id || request.packageSourceId)
  if (explicit) return explicit
  return cloneArray(visual.source_ids || visual.sourceIds).map(asText).find((sourceId) => sourceId.startsWith(CARRIER_PACKAGE_PREFIX)) || ''
}

export function isPptCarrierSnapshotRequest(visual = {}) {
  const data = cloneObject(visual.data)
  return asText(visual.visual_type || visual.visualType) === 'existing_asset'
    && asText(visual.status) === 'needs_existing_asset'
    && asText(data.composition || data.composition_type || data.compositionType) === 'carrier_snapshot_request'
    && !!carrierPackageSourceIdFromVisual(visual)
}

function findCarrierPackageSource(sources = [], packageSourceId = '') {
  return cloneArray(sources).find((source) => asText(source && source.id) === packageSourceId) || null
}

function carrierHasGeometry(carrier = {}) {
  const geometry = cloneObject(carrier.geometry)
  return cloneArray(geometry.polygon).length >= 3 || cloneArray(geometry.boundary).length >= 2
}

function normalizeCarrierRequest(request = {}) {
  return {
    ...cloneObject(request),
    title: asText(request.title) || '核心空间载体分布图',
    package_source_id: asText(request.package_source_id || request.packageSourceId),
    focus_carrier_ids: cloneArray(request.focus_carrier_ids || request.focusCarrierIds).map(asText).filter(Boolean).slice(0, 8),
    extent_mode: asText(request.extent_mode || request.extentMode) === 'local' ? 'local' : 'all',
  }
}

function carrierTypeColor(type = '') {
  if (type === 'block_loop') return { fill: '#fed7aa', stroke: '#c2410c' }
  if (type === 'corridor') return { fill: 'none', stroke: '#2563eb' }
  return { fill: 'none', stroke: '#0f766e' }
}

function renderCarrierSnapshotSvg(model = {}, request = {}, packagePayload = {}) {
  const width = Number(model.width || 1000) || 1000
  const height = Number(model.height || 620) || 620
  const title = escapeXml(request.title || packagePayload.title || '核心空间载体分布图')
  const subtitle = escapeXml(packagePayload.summary || 'POI × 路网 × 人口 × 夜光空间载体')
  const parts = [
    `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="${escapeXml(model.viewBox || `0 0 ${width} ${height}`)}">`,
    '<rect x="0" y="0" width="100%" height="100%" fill="#f8fafc"/>',
    '<rect x="24" y="24" width="952" height="572" rx="18" fill="#eef2f7" stroke="#dbe3ef"/>',
  ]
  cloneArray(model.roadItems).forEach((road) => {
    const stroke = road.isSkeleton ? '#334155' : '#94a3b8'
    const widthValue = road.isSkeleton ? 4.2 : 2
    const opacity = road.isSkeleton ? 0.72 : 0.42
    parts.push(`<path d="${escapeXml(road.path)}" fill="none" stroke="${stroke}" stroke-width="${widthValue}" stroke-linecap="round" stroke-linejoin="round" opacity="${opacity}"/>`)
  })
  cloneArray(model.items).forEach((item) => {
    const colors = carrierTypeColor(asText(item.type))
    const active = item.isFocus || !cloneArray(request.focus_carrier_ids).length
    if (item.type === 'block_loop' && item.polygonPath) {
      parts.push(`<path d="${escapeXml(item.polygonPath)}" fill="${colors.fill}" fill-opacity="${active ? '0.68' : '0.36'}" stroke="none"/>`)
    }
    const path = asText(item.outlinePath || item.boundaryPath || item.polygonPath)
    if (path) {
      parts.push(`<path d="${escapeXml(path)}" fill="none" stroke="${colors.stroke}" stroke-width="${active ? '5' : '3'}" stroke-linecap="round" stroke-linejoin="round" opacity="${active ? '0.95' : '0.48'}"/>`)
    }
    if (active || cloneArray(model.items).length <= 6) {
      const label = escapeXml(asText(item.id).replace('block_loop_', 'L').replace('corridor_', 'C').replace('segment_', 'S'))
      parts.push(`<text x="${escapeXml(item.labelX)}" y="${escapeXml(item.labelY)}" text-anchor="middle" dominant-baseline="central" font-family="Arial,sans-serif" font-size="22" font-weight="700" fill="#0f172a" paint-order="stroke" stroke="#ffffff" stroke-width="5">${label}</text>`)
    }
  })
  parts.push(`<text x="54" y="64" font-family="Arial,sans-serif" font-size="28" font-weight="700" fill="#0f172a">${title}</text>`)
  if (subtitle) {
    parts.push(`<text x="54" y="96" font-family="Arial,sans-serif" font-size="15" fill="#475569">${subtitle}</text>`)
  }
  parts.push('<g transform="translate(54 548)" font-family="Arial,sans-serif" font-size="13" fill="#475569">')
  parts.push('<circle cx="0" cy="0" r="5" fill="#fed7aa" stroke="#c2410c" stroke-width="2"/><text x="12" y="4">街区/loop</text>')
  parts.push('<line x1="112" y1="0" x2="142" y2="0" stroke="#2563eb" stroke-width="4" stroke-linecap="round"/><text x="150" y="4">廊道</text>')
  parts.push('<line x1="222" y1="0" x2="252" y2="0" stroke="#0f766e" stroke-width="4" stroke-linecap="round"/><text x="260" y="4">路段</text>')
  parts.push('</g></svg>')
  return parts.join('')
}

export async function capturePptCarrierSnapshotAsset(request = {}, options = {}) {
  const normalized = normalizeCarrierRequest(request)
  if (!normalized.package_source_id) throw new Error('ppt_carrier_package_missing')
  const source = findCarrierPackageSource(options.sources, normalized.package_source_id)
  if (!source) throw new Error('ppt_carrier_package_missing')
  const packagePayload = cloneObject(cloneObject(source.meta).package)
  const carriers = cloneArray(packagePayload.carriers)
  if (!carriers.length) throw new Error('ppt_carrier_package_carriers_missing')
  if (!carriers.some(carrierHasGeometry)) throw new Error('ppt_carrier_geometry_missing')
  const focusIds = normalized.focus_carrier_ids.length ? normalized.focus_carrier_ids : carriers.slice(0, 1).map((carrier) => asText(carrier.carrier_id)).filter(Boolean)
  const model = buildPptCarrierPreviewModel(carriers, {
    roadContext: cloneObject(packagePayload.road_context || packagePayload.roadContext),
    focusIds,
    extentMode: normalized.extent_mode,
    width: Number(options.width || 1000) || 1000,
    height: Number(options.height || 620) || 620,
  })
  if (!cloneArray(model.items).length) throw new Error('ppt_carrier_snapshot_empty')
  const svg = renderCarrierSnapshotSvg(model, { ...normalized, focus_carrier_ids: focusIds }, packagePayload)
  const dataUrl = `data:image/svg+xml;base64,${encodeBase64Utf8(svg)}`
  if (!isImageDataUrl(dataUrl)) throw new Error('ppt_carrier_snapshot_render_failed')
  const digest = `${normalized.package_source_id.split(':').pop() || 'carrier'}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
  return {
    asset_id: `ppt-carrier-snapshot-${digest}`,
    asset_kind: 'map_snapshot',
    kind: 'map_snapshot',
    source: 'frontend_carrier_package_snapshot',
    title: normalized.title,
    data_url: dataUrl,
    status: 'ready',
    captured_at: new Date().toISOString(),
    data: {
      composition: 'carrier_snapshot',
      package_source_id: normalized.package_source_id,
      carrier_snapshot_request: normalized,
    },
  }
}
