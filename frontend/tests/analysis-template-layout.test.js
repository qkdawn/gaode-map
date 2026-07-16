import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'

import { parse } from '@vue/compiler-dom'


function hasClass(node, className) {
  if (!node || node.type !== 1) return false
  const classAttr = node.props.find((prop) => prop.type === 6 && prop.name === 'class')
  const classes = String(classAttr && classAttr.value && classAttr.value.content || '').split(/\s+/)
  return classes.includes(className)
}

function findElement(node, predicate) {
  if (predicate(node)) return node
  for (const child of node.children || []) {
    const found = findElement(child, predicate)
    if (found) return found
  }
  return null
}

test('analysis map remains inside the main workspace layout', () => {
  const sidebar = fs.readFileSync(new URL('../src/pages/analysis/components/sidebar.html', import.meta.url), 'utf8')
  const main = fs.readFileSync(new URL('../src/pages/analysis/components/main.html', import.meta.url), 'utf8')
  const ast = parse(`<div class="analysis-layout-root">${sidebar}${main}</div>`)

  assert.equal(ast.children.length, 1)
  const layoutRoot = ast.children[0]
  assert.equal(hasClass(layoutRoot, 'analysis-layout-root'), true)

  const mainContent = findElement(layoutRoot, (node) => hasClass(node, 'main-content'))
  assert.ok(mainContent, 'main workspace must exist inside analysis-layout-root')

  const mapStage = findElement(mainContent, (node) => hasClass(node, 'analysis-map-stage'))
  assert.ok(mapStage, 'analysis-map-stage must remain inside main-content')

  const mapContainer = findElement(mapStage, (node) => (
    node.type === 1
    && node.props.some((prop) => prop.type === 6 && prop.name === 'id' && prop.value?.content === 'container')
  ))
  assert.ok(mapContainer, '#container must remain inside analysis-map-stage')
})
