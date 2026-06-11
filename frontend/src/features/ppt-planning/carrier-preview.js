function asFiniteNumber(value) {
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

function roundPathValue(value) {
  return Number(value || 0).toFixed(2).replace(/\.?0+$/, '')
}

function clamp01(value) {
  const number = asFiniteNumber(value)
  if (number === null) return 0
  return Math.max(0, Math.min(1, number))
}

export function normalizeCarrierPreviewPoints(points = []) {
  if (!Array.isArray(points)) return []
  return points.map((point) => {
    if (Array.isArray(point) && point.length >= 2) {
      const lng = asFiniteNumber(point[0])
      const lat = asFiniteNumber(point[1])
      return lng === null || lat === null ? null : [lng, lat]
    }
    if (point && typeof point === 'object') {
      const lng = asFiniteNumber(point.lng ?? point.longitude ?? point.x)
      const lat = asFiniteNumber(point.lat ?? point.latitude ?? point.y)
      return lng === null || lat === null ? null : [lng, lat]
    }
    return null
  }).filter(Boolean)
}

function normalizeRoadPreviewFeatures(roadContext = {}) {
  const features = roadContext && typeof roadContext === 'object'
    ? (roadContext.features || roadContext.items)
    : []
  if (!Array.isArray(features)) return []
  return features.map((feature, index) => {
    const path = normalizeCarrierPreviewPoints(feature?.path || feature?.coordinates || feature?.geometry?.coordinates)
    if (path.length < 2) return null
    const skeletonScore = clamp01(feature?.skeleton_score ?? feature?.skeletonScore)
    const choiceScore = clamp01(feature?.choice_score ?? feature?.choiceScore)
    const integrationScore = clamp01(feature?.integration_score ?? feature?.integrationScore)
    return {
      id: String(feature?.id || `road_${index + 1}`),
      path,
      isSkeleton: !!(feature?.is_skeleton ?? feature?.isSkeleton),
      skeletonScore,
      choiceScore,
      integrationScore,
      points: path,
    }
  }).filter(Boolean)
}

function buildSvgPath(points = [], closed = false) {
  if (closed && points.length < 3) return ''
  if (!closed && points.length < 2) return ''
  const commands = points.map((point, index) => {
    const prefix = index === 0 ? 'M' : 'L'
    return `${prefix} ${roundPathValue(point.x)} ${roundPathValue(point.y)}`
  })
  return `${commands.join(' ')}${closed ? ' Z' : ''}`
}

function centroid(points = []) {
  if (!points.length) return { x: 0, y: 0 }
  const total = points.reduce((acc, point) => ({ x: acc.x + point.x, y: acc.y + point.y }), { x: 0, y: 0 })
  return { x: total.x / points.length, y: total.y / points.length }
}

export function buildPptCarrierPreviewModel(carriers = [], options = {}) {
  const width = Number(options.width || 1000) || 1000
  const height = Number(options.height || 620) || 620
  const padding = Number(options.padding || 54) || 54
  const extentMode = String(options.extentMode || options.previewMode || 'local') === 'all' ? 'all' : 'local'
  const viewBox = `0 0 ${width} ${height}`
  const roadRecords = normalizeRoadPreviewFeatures(options.roadContext || options.road_context)
  const focusIds = new Set((Array.isArray(options.focusIds) ? options.focusIds : [options.focusId])
    .map((item) => String(item || ''))
    .filter(Boolean))
  const records = (Array.isArray(carriers) ? carriers : []).map((carrier, index) => {
    const geometry = carrier && typeof carrier.geometry === 'object' ? carrier.geometry : {}
    const polygon = normalizeCarrierPreviewPoints(geometry.polygon)
    const boundary = normalizeCarrierPreviewPoints(geometry.boundary)
    const points = [...polygon, ...boundary]
    const id = String((carrier && carrier.carrier_id) || `carrier_${index + 1}`)
    return {
      id,
      type: String((carrier && carrier.carrier_type) || 'segment'),
      label: String((carrier && carrier.carrier_label) || '空间载体'),
      polygon,
      boundary,
      points,
      isFocus: focusIds.size > 0 && focusIds.has(id),
    }
  }).filter((item) => item.points.length)

  const focusedRecords = records.filter((item) => item.isFocus)
  const carrierBoundsPoints = (extentMode === 'local' && focusedRecords.length ? focusedRecords : records).flatMap((item) => item.points)
  const allBoundsPoints = extentMode === 'all'
    ? [...carrierBoundsPoints, ...roadRecords.flatMap((item) => item.points)]
    : carrierBoundsPoints
  const boundsPoints = allBoundsPoints.length ? allBoundsPoints : roadRecords.flatMap((item) => item.points)
  if (!boundsPoints.length) return { viewBox, width, height, extentMode, items: [], roadItems: [] }

  const lngValues = boundsPoints.map((point) => point[0])
  const latValues = boundsPoints.map((point) => point[1])
  const minLng = Math.min(...lngValues)
  const maxLng = Math.max(...lngValues)
  const minLat = Math.min(...latValues)
  const maxLat = Math.max(...latValues)
  const drawWidth = Math.max(1, width - padding * 2)
  const drawHeight = Math.max(1, height - padding * 2)
  const meanLatRad = ((minLat + maxLat) / 2) * Math.PI / 180
  const lngScale = Math.max(0.1, Math.cos(meanLatRad))
  const projectedBounds = boundsPoints.map((point) => ({
    x: (point[0] - minLng) * lngScale,
    y: point[1] - minLat,
  }))
  const minX = Math.min(...projectedBounds.map((point) => point.x))
  const maxX = Math.max(...projectedBounds.map((point) => point.x))
  const minY = Math.min(...projectedBounds.map((point) => point.y))
  const maxY = Math.max(...projectedBounds.map((point) => point.y))
  const xSpan = Math.max(maxX - minX, 0.000001)
  const ySpan = Math.max(maxY - minY, 0.000001)
  const scale = Math.min(drawWidth / xSpan, drawHeight / ySpan)
  const contentWidth = xSpan * scale
  const contentHeight = ySpan * scale
  const offsetX = padding + (drawWidth - contentWidth) / 2
  const offsetY = padding + (drawHeight - contentHeight) / 2

  function project(point) {
    const projectedX = (point[0] - minLng) * lngScale
    const projectedY = point[1] - minLat
    return {
      x: offsetX + (projectedX - minX) * scale,
      y: offsetY + (maxY - projectedY) * scale,
    }
  }

  const roadItems = roadRecords.map((item) => ({
    id: item.id,
    path: buildSvgPath(item.path.map(project), false),
    isSkeleton: item.isSkeleton,
    skeletonScore: item.skeletonScore,
    choiceScore: item.choiceScore,
    integrationScore: item.integrationScore,
    className: [
      item.isSkeleton ? 'is-skeleton' : '',
      item.skeletonScore >= 0.62 ? 'is-high-score' : '',
    ].filter(Boolean).join(' '),
  })).filter((item) => item.path)

  const items = records.map((item) => {
    const polygonPoints = item.polygon.map(project)
    const boundaryPoints = item.boundary.map(project)
    const labelAnchor = centroid(polygonPoints.length ? polygonPoints : boundaryPoints)
    const polygonPath = buildSvgPath(polygonPoints, true)
    const boundaryPath = buildSvgPath(boundaryPoints, false)
    return {
      id: item.id,
      type: item.type,
      label: item.label,
      polygonPath,
      boundaryPath,
      outlinePath: item.type === 'block_loop'
        ? (polygonPath || boundaryPath)
        : (boundaryPath || polygonPath),
      labelX: roundPathValue(labelAnchor.x),
      labelY: roundPathValue(labelAnchor.y),
      isFocus: item.isFocus,
    }
  }).sort((a, b) => Number(a.isFocus) - Number(b.isFocus))

  return { viewBox, width, height, extentMode, items, roadItems }
}
