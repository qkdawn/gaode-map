import {
  asText,
  canonicalPptSourceKind,
  cloneArray,
  cloneObject,
} from './base.js'
import {
  createDefaultPptSources,
  normalizePptSource,
} from './model.js'

export const PPT_UNCATEGORIZED_GROUP_ID = 'group:uncategorized'

function uniqueText(items = []) {
  const seen = new Set()
  const values = []
  cloneArray(items).forEach((item) => {
    const value = asText(item)
    if (value && !seen.has(value)) {
      seen.add(value)
      values.push(value)
    }
  })
  return values
}

export function stableGroupId(title = '', fallback = '') {
  const slug = asText(title)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
  return slug ? `group:${slug}` : asText(fallback) || PPT_UNCATEGORIZED_GROUP_ID
}

export function simpleHash(value = '') {
  const text = asText(value)
  let hash = 0
  for (let index = 0; index < text.length; index += 1) {
    hash = ((hash << 5) - hash + text.charCodeAt(index)) | 0
  }
  return Math.abs(hash).toString(36)
}

export function normalizeSources(seedSources = []) {
  const rawSources = cloneArray(seedSources).length ? cloneArray(seedSources) : createDefaultPptSources()
  return rawSources.map(normalizePptSource).filter((item) => item.id)
}

export function getDefaultGroupSpecForSource(source = {}) {
  const sourceId = asText(source.id)
  const sourceKind = canonicalPptSourceKind(source.source_kind || source.sourceKind || (source.meta || {}).sourceKind, sourceId)
  if (sourceKind === 'package' || sourceKind === 'package-placeholder' || sourceId.startsWith('package:') || sourceId.startsWith('package-placeholder:')) {
    return { id: 'group:packages', title: '资料包', emoji: '' }
  }
  if (sourceKind === 'document' || sourceId.startsWith('document:')) {
    return { id: 'group:document-evidence', title: '文档库', emoji: '' }
  }
  if (sourceKind === 'web') {
    return { id: 'group:web', title: '联网资料', emoji: '' }
  }
  if (sourceKind === 'database' || sourceId.startsWith('database:')) {
    return { id: 'group:database', title: '数据库源', emoji: '' }
  }
  if (['current:scope', 'current:dataset:h3'].includes(sourceId)) {
    return { id: 'group:spatial-scope', title: '空间范围与网格', emoji: '' }
  }
  if (['current:dataset:poi', 'current:analysis:poi_h3', 'current:analysis:nightlight'].includes(sourceId)) {
    return { id: 'group:urban-vitality', title: '城市活力证据', emoji: '' }
  }
  if (sourceId === 'current:analysis:population') {
    return { id: 'group:population-demand', title: '人群与需求', emoji: '' }
  }
  if (sourceId === 'current:analysis:road') {
    return { id: 'group:accessibility', title: '交通与可达性', emoji: '' }
  }
  return { id: '', title: '', emoji: '' }
}

export function normalizePptSourceGroup(seed = {}) {
  const sourceIds = uniqueText(seed.sourceIds || seed.source_ids)
  const title = asText(seed.title) || '未分类来源'
  return {
    id: asText(seed.id) || stableGroupId(title),
    title,
    emoji: asText(seed.emoji),
    sourceIds,
    collapsed: !!seed.collapsed,
    meta: cloneObject(seed.meta),
  }
}

export function createDefaultPptSourceGroups(sources = []) {
  const groupMap = new Map()
  cloneArray(sources).forEach((source) => {
    const spec = getDefaultGroupSpecForSource(source)
    if (!spec.id) return
    if (!groupMap.has(spec.id)) {
      groupMap.set(spec.id, {
        id: spec.id,
        title: spec.title,
        emoji: spec.emoji,
        sourceIds: [],
        collapsed: false,
        meta: { source: 'default' },
      })
    }
    groupMap.get(spec.id).sourceIds.push(asText(source.id))
  })
  return Array.from(groupMap.values()).filter((group) => group.sourceIds.length)
}

export function reconcilePptSourceGroups(seedGroups = [], sources = [], ungroupedSourceIds = []) {
  const sourceIds = cloneArray(sources).map((item) => asText(item.id)).filter(Boolean)
  const allowed = new Set(sourceIds)
  const ungrouped = new Set(uniqueText(ungroupedSourceIds))
  const seen = new Set()
  const normalizedGroups = cloneArray(seedGroups)
    .map(normalizePptSourceGroup)
    .filter((group) => group.id !== PPT_UNCATEGORIZED_GROUP_ID)
    .map((group) => {
      const groupSourceIds = group.sourceIds.filter((sourceId) => {
        if (!allowed.has(sourceId) || seen.has(sourceId) || ungrouped.has(sourceId)) return false
        seen.add(sourceId)
        return true
      })
      return { ...group, sourceIds: groupSourceIds }
    })
    .filter((group) => group.sourceIds.length)

  const groupById = new Map(normalizedGroups.map((group) => [group.id, group]))
  sourceIds.forEach((sourceId) => {
    if (seen.has(sourceId) || ungrouped.has(sourceId)) return
    const source = cloneArray(sources).find((item) => asText(item.id) === sourceId)
    const spec = getDefaultGroupSpecForSource(source)
    if (!spec.id) return
    const group = groupById.get(spec.id) || {
      id: spec.id,
      title: spec.title,
      emoji: spec.emoji,
      sourceIds: [],
      collapsed: false,
      meta: { source: 'default' },
    }
    group.sourceIds = [...group.sourceIds, sourceId]
    if (!groupById.has(spec.id)) {
      groupById.set(spec.id, group)
      normalizedGroups.push(group)
    }
    seen.add(sourceId)
  })

  return normalizedGroups
}

export function sourceIdsFromSources(sources = []) {
  return cloneArray(sources).map((item) => asText(item.id)).filter(Boolean)
}

export function getReadySelectedSourceIds(sources = []) {
  return cloneArray(sources)
    .filter((item) => item && item.selected && asText(item.status) === 'ready')
    .map((item) => asText(item.id))
    .filter(Boolean)
}

export function syncSpecSourceIds(normalized = {}, sources = []) {
  return {
    ...normalized.spec,
    sourceIds: getReadySelectedSourceIds(sources),
  }
}

export function ensureGroupForSourceIds(groups = [], groupId = '', sourceIds = []) {
  const ids = uniqueText(sourceIds)
  const id = asText(groupId)
  if (!ids.length) return cloneArray(groups)
  if (!id || id === PPT_UNCATEGORIZED_GROUP_ID) return cloneArray(groups)
  const nextGroups = cloneArray(groups).map(normalizePptSourceGroup)
  const existing = nextGroups.find((group) => group.id === id)
  if (existing) {
    existing.sourceIds = uniqueText([...existing.sourceIds, ...ids])
    existing.collapsed = false
    return nextGroups
  }
  return [
    ...nextGroups,
    {
      id,
      title: '未分类来源',
      emoji: '',
      sourceIds: ids,
      collapsed: false,
      meta: { source: 'manual' },
    },
  ]
}
