import assert from 'node:assert/strict'
import fs from 'node:fs'
import test from 'node:test'
import vm from 'node:vm'

function loadMapCore(AMap) {
  const filename = new URL('../src/map/core.js', import.meta.url)
  const source = fs.readFileSync(filename, 'utf8')
    .replace(/^import .*$/m, 'const MapUtils = {}')
    .replace(/export \{ MapCore \};\s*$/, 'globalThis.MapCore = MapCore;')
  const context = { AMap, URLSearchParams, window: { AMap, location: { search: '' } } }
  vm.runInNewContext(source, context, { filename: 'core.js' })
  return context.MapCore
}

function createOverlayClass(kind, created) {
  return class {
    constructor(options) {
      this.kind = kind
      this.options = options
      this.mapCalls = []
      this.handlers = {}
      created.push(this)
    }

    setMap(map) {
      this.mapCalls.push(map)
    }

    on(event, handler) {
      this.handlers[event] = handler
    }
  }
}

test('MapCore renders authoritative GeoJSON focus and replaces the previous overlay', () => {
  const created = []
  const AMap = {
    Marker: createOverlayClass('marker', created),
    Polyline: createOverlayClass('polyline', created),
    Polygon: createOverlayClass('polygon', created),
  }
  const MapCore = loadMapCore(AMap)
  const fitCalls = []
  const map = { setFitView: (...args) => fitCalls.push(args) }
  const oldOverlay = { mapCalls: [], setMap(value) { this.mapCalls.push(value) } }
  const core = Object.create(MapCore.prototype)
  core.map = map
  core.focusedSpatialOverlays = [oldOverlay]
  let clicked = 0

  const focused = core.focusSpatialFeature({
    type: 'Feature',
    geometry: {
      type: 'MultiLineString',
      coordinates: [
        [[112, 28], [112.01, 28.01]],
        [[112.02, 28.02], [112.03, 28.03]],
      ],
    },
  }, { onClick: () => { clicked += 1 } })

  assert.equal(focused, true)
  assert.deepEqual(oldOverlay.mapCalls, [null])
  assert.equal(core.focusedSpatialOverlays.length, 2)
  assert.equal(created[0].kind, 'polyline')
  assert.deepEqual(created[0].options.path, [[112, 28], [112.01, 28.01]])
  assert.equal(created[0].mapCalls[0], map)
  created[0].handlers.click()
  assert.equal(clicked, 1)
  assert.equal(fitCalls.length, 1)
  assert.equal(fitCalls[0][0].length, 2)
})

test('MapCore preserves polygon rings and rejects unsupported geometry', () => {
  const created = []
  const AMap = {
    Marker: createOverlayClass('marker', created),
    Polyline: createOverlayClass('polyline', created),
    Polygon: createOverlayClass('polygon', created),
  }
  const MapCore = loadMapCore(AMap)
  const core = Object.create(MapCore.prototype)
  core.map = { setFitView() {} }
  core.focusedSpatialOverlays = []
  const rings = [
    [[112, 28], [112.02, 28], [112.02, 28.02], [112, 28]],
    [[112.005, 28.005], [112.01, 28.005], [112.01, 28.01], [112.005, 28.005]],
  ]

  assert.equal(core.focusSpatialFeature({ type: 'Feature', geometry: { type: 'Polygon', coordinates: rings } }), true)
  assert.deepEqual(created[0].options.path, rings)
  assert.equal(core.focusSpatialFeature({ type: 'Feature', geometry: { type: 'GeometryCollection', geometries: [] } }), false)
  assert.equal(core.focusedSpatialOverlays.length, 1)
})
