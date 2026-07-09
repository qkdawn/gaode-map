import {
  asText,
  canonicalPptSourceKind,
  cloneArray,
  cloneObject,
} from './base.js'
import {
  evidenceNodesFromAiPayload,
  evidenceNodesFromEvidenceItems,
} from '../analysis-sources/evidence-nodes.js'

function normalizeTextList(value, limit = 3, itemLimit = 120) {
  const rawItems = Array.isArray(value) ? value : [value]
  const items = []
  rawItems.forEach((raw) => {
    const text = raw && typeof raw === 'object'
      ? asText(raw.text || raw.description || raw.source || raw.method)
      : asText(raw)
    if (!text) return
    text.split(/[\n；;]+/).forEach((part) => {
      const clean = asText(part).replace(/^[\-*\d.、)\s]+/, '').trim()
      if (clean && items.length < limit) items.push(clean.slice(0, itemLimit))
    })
  })
  return items
}

function compactObject(value = {}, keys = []) {
  const source = cloneObject(value)
  const compact = {}
  keys.forEach((key) => {
    const item = source[key]
    if (item !== undefined && item !== null && item !== '' && !(Array.isArray(item) && !item.length)) {
      compact[key] = item
    }
  })
  return compact
}

function metricSourceIds(metric = {}) {
  return cloneArray(metric.source_ids || metric.sourceIds)
    .map((sourceId) => asText(sourceId))
    .filter(Boolean)
}

function createEvidenceItem({
  sourceId = '',
  sourceTitle = '',
  type = '',
  title = '',
  text = '',
  payload = {},
} = {}) {
  const node = createEvidenceNode({
    sourceId,
    sourceTitle,
    sourceType: 'system',
    evidenceLevel: type,
    title,
    content: text,
    metadata: payload,
  })
  return pptEvidenceFromNode(node, sourceTitle)
}

function createEvidenceNode({
  sourceId = '',
  sourceTitle = '',
  sourceType = 'system',
  evidenceLevel = 'source_evidence',
  title = '',
  content = '',
  summary = '',
  metadata = {},
  locator = '',
  citation = '',
} = {}) {
  const resolvedSourceId = asText(sourceId)
  const resolvedTitle = asText(title) || asText(sourceTitle) || '证据'
  const resolvedLevel = asText(evidenceLevel) || 'source_evidence'
  const safeMetadata = cloneObject(metadata)
  const stableKey = asText(safeMetadata.metric_ids && safeMetadata.metric_ids[0])
    || asText(safeMetadata.summary_key)
    || asText(safeMetadata.count ? `count:${safeMetadata.count}` : '')
    || resolvedTitle
  const nodeId = `${resolvedSourceId}:evidence:${resolvedLevel}:${stableKey}`.replace(/\s+/g, '-')
  return {
    id: nodeId,
    source_id: resolvedSourceId,
    sourceId: resolvedSourceId,
    source_type: asText(sourceType) || 'system',
    sourceType: asText(sourceType) || 'system',
    title: resolvedTitle,
    content: asText(content),
    summary: asText(summary || content).slice(0, 260),
    metadata: safeMetadata,
    locator: asText(locator || safeMetadata.locator),
    score: 0,
    evidence_level: resolvedLevel,
    evidenceLevel: resolvedLevel,
    warnings: cloneArray(safeMetadata.warnings),
    citation: asText(citation),
  }
}

function pptEvidenceFromNode(node = {}, sourceTitle = '') {
  const metadata = cloneObject(node.metadata)
  metadata.evidence_node_id = asText(node.id)
  metadata.source_id = asText(node.source_id || node.sourceId)
  metadata.source_type = asText(node.source_type || node.sourceType)
  metadata.locator = asText(node.locator)
  return {
    source_id: asText(node.source_id || node.sourceId),
    sourceId: asText(node.source_id || node.sourceId),
    source_title: asText(sourceTitle || node.title),
    sourceTitle: asText(sourceTitle || node.title),
    type: asText(node.evidence_level || node.evidenceLevel),
    title: asText(node.title),
    text: asText(node.content),
    citation: asText(node.citation),
    payload: metadata,
  }
}

function createAiPayload({
  sourceId = '',
  title = '',
  sourceKind = 'system',
  scope = null,
  metrics = [],
  metricGaps = [],
  evidence = [],
  visualSpecs = [],
  excluded = [],
  policy = '',
} = {}) {
  const normalizedScope = scope && typeof scope === 'object' ? cloneObject(scope) : null
  const readyMetrics = cloneArray(metrics).filter((metric) => asText(metric.status) === 'ready')
  const gaps = cloneArray(metricGaps)
  const evidenceItems = cloneArray(evidence).filter((item) => asText(item.title || item.text))
  const visuals = cloneArray(visualSpecs).filter((item) => asText(item.visual_id || item.visualId || item.title))
  const included = []
  if (normalizedScope) included.push('scope')
  if (readyMetrics.length) included.push('metrics')
  if (gaps.length) included.push('metric_gaps')
  if (evidenceItems.length) included.push('evidence')
  if (visuals.length) included.push('visual_specs')
  const payload = {
    version: 'ppt_ai_input_block_v1',
    source_id: asText(sourceId),
    sourceId: asText(sourceId),
    title: asText(title),
    source_kind: asText(sourceKind),
    sourceKind: asText(sourceKind),
    included,
    scope: normalizedScope,
    metrics: readyMetrics,
    metric_gaps: gaps,
    metricGaps: gaps,
    visual_specs: visuals,
    visualSpecs: visuals,
    excluded: cloneArray(excluded),
    counts: {
      scope: normalizedScope ? 1 : 0,
      metrics: readyMetrics.length,
      metric_gaps: gaps.length,
      evidence: evidenceItems.length,
      visual_specs: visuals.length,
    },
    policy: asText(policy) || '生成时只发送这个 AI 输入块；原始大数据不进入 LLM。',
  }
  const evidenceNodes = evidenceNodesFromEvidenceItems(payload, evidenceItems)
  return {
    ...payload,
    evidence_nodes: evidenceNodes,
    evidenceNodes,
  }
}

export function createPptTransportFromAiPayload(aiPayload = {}) {
  const payload = cloneObject(aiPayload)
  const counts = cloneObject(payload.counts)
  const evidenceNodes = evidenceNodesFromAiPayload(payload)
  const scopeCount = Number(counts.scope ?? payload.scope_count ?? payload.scopeCount ?? 0) || 0
  const metricCount = Number(counts.metrics ?? payload.metric_count ?? payload.metricCount ?? 0) || 0
  const metricGapCount = Number(counts.metric_gaps ?? counts.metricGaps ?? 0) || 0
  const evidenceCount = Number(payload.evidence_count ?? payload.evidenceCount ?? evidenceNodes.length ?? counts.evidence ?? 0) || 0
  const visualSpecCount = Number(counts.visual_specs ?? counts.visualSpecs ?? 0) || 0
  const included = cloneArray(payload.included)
    .map((item) => asText(item))
    .filter(Boolean)
  if (evidenceNodes.length && !included.includes('evidence')) included.push('evidence')
  return {
    source_id: asText(payload.source_id || payload.sourceId),
    sourceId: asText(payload.source_id || payload.sourceId),
    title: asText(payload.title),
    source_kind: asText(payload.source_kind || payload.sourceKind),
    sourceKind: asText(payload.source_kind || payload.sourceKind),
    transport_status: included.length ? 'ready_to_send' : 'selected_no_payload',
    transportStatus: included.length ? 'ready_to_send' : 'selected_no_payload',
    included,
    metric_count: metricCount,
    metricCount,
    metric_gap_count: metricGapCount,
    metricGapCount,
    evidence_count: evidenceCount,
    evidenceCount,
    scope_count: scopeCount,
    scopeCount,
    visual_spec_count: visualSpecCount,
    visualSpecCount,
    excluded: cloneArray(payload.excluded),
    policy: asText(payload.policy),
    preview: true,
  }
}

export const DEFAULT_PPT_PAGE_COUNT = 15
export const PPT_PLANNING_STEPS = Object.freeze({
  MATERIALS: 'materials',
  OUTLINE_GENERATING: 'outline_generating',
  OUTLINE_READY: 'outline_ready',
  NARRATIVE_GENERATING: 'narrative_generating',
  NARRATIVE_READY: 'narrative_ready',
  SLIDES_GENERATING: 'slides_generating',
  DIRECTIVE_DRAFT: 'directive_draft',
  VISUALS_READY: 'visuals_ready',
})

const SYSTEM_SOURCE_DEFINITIONS = Object.freeze([
  {
    id: 'current:scope',
    type: 'data',
    title: '当前等时圈范围',
    label: '空间范围',
    taskKey: 'scope',
  },
  {
    id: 'current:dataset:poi',
    type: 'data',
    title: 'POI 基础数据',
    label: '基础数据',
    taskKey: 'poi_fetch',
  },
  {
    id: 'current:dataset:h3',
    type: 'sheet',
    title: 'H3 / 共享网格',
    label: '基础网格',
    taskKey: 'poi_h3_grid',
  },
  {
    id: 'current:analysis:poi_h3',
    type: 'sheet',
    title: 'POI / H3 空间结构分析',
    label: '空间结构',
    taskKey: 'poi_h3_grid',
  },
  {
    id: 'current:analysis:population',
    type: 'data',
    title: '人口结构分析',
    label: '分析结果',
    taskKey: 'population',
  },
  {
    id: 'current:analysis:nightlight',
    type: 'data',
    title: '夜光强度分析',
    label: '分析结果',
    taskKey: 'nightlight',
  },
  {
    id: 'current:analysis:road',
    type: 'data',
    title: '路网与可达性分析',
    label: '分析结果',
    taskKey: 'road_syntax',
  },
])

function hasRing(value) {
  return Array.isArray(value) && value.length >= 3
}

function hasScopeSource(context = {}) {
  const scope = context.scope && typeof context.scope === 'object' ? context.scope : {}
  return !!(
    context.scopeReady
    || hasRing(scope.polygon)
    || hasRing(scope.drawn_polygon)
    || hasRing(scope.drawnPolygon)
    || scope.isochrone_feature
    || scope.isochroneFeature
  )
}

function hasSummarySource(context = {}) {
  const payloads = context.panelPayloads && typeof context.panelPayloads === 'object' ? context.panelPayloads : {}
  const summaryPack = context.summaryPack || payloads.summary_pack || payloads.summaryPack
  return !!(
    context.summaryReady
    || (summaryPack && typeof summaryPack === 'object' && Object.keys(summaryPack).length)
  )
}

function hasTaskSource(context = {}, taskKey = '') {
  const results = context.taskResults && typeof context.taskResults === 'object' ? context.taskResults : {}
  return !!results[taskKey]
}

function getSystemSourceReady(context = {}, taskKey = '') {
  if (taskKey === 'scope') return hasScopeSource(context)
  if (taskKey === 'summary') return hasSummarySource(context)
  return hasTaskSource(context, taskKey)
}

function getDefaultGroupSpecForSource(source = {}) {
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

function isRetainedUserSource(source = {}) {
  const sourceKind = canonicalPptSourceKind(source.source_kind || source.sourceKind || (source.meta && source.meta.sourceKind), source.id)
  const sourceId = asText(source.id)
  return ['package', 'document', 'image', 'web', 'database'].includes(sourceKind)
    || sourceId.startsWith('document:')
    || sourceId.startsWith('image:')
    || sourceId.startsWith('package:')
    || sourceId.startsWith('database:')
}

function getSourceDetail(context = {}, taskKey = '') {
  const details = context.sourceDetails && typeof context.sourceDetails === 'object' ? context.sourceDetails : {}
  return asText(details[taskKey])
}

function getCurrentSourceDetail(context = {}, sourceId = '', fallbackTaskKey = '') {
  const details = context.sourceDetails && typeof context.sourceDetails === 'object' ? context.sourceDetails : {}
  return asText(details[sourceId]) || getSourceDetail(context, fallbackTaskKey)
}

function createSourceTransportPreview({
  sourceId = '',
  title = '',
  sourceKind = 'system',
  metricCount = 0,
  evidenceCount = 0,
  scopeCount = 0,
  excludedType = 'current_raw_payload',
  excludedReason = '不传完整原始数据，只传已构建的指标和轻量证据。',
} = {}) {
  return createPptTransportFromAiPayload(createAiPayload({
    sourceId,
    title,
    sourceKind,
    scope: Number(scopeCount || 0) > 0 ? { type: 'scope_brief' } : null,
    metrics: Array.from({ length: Number(metricCount || 0) || 0 }, (_item, index) => ({
      metric_id: `preview:metric:${index + 1}`,
      domain: 'preview',
      label: 'preview',
      value: index + 1,
      status: 'ready',
    })),
    evidence: Array.from({ length: Number(evidenceCount || 0) || 0 }, (_item, index) => ({
      title: `evidence ${index + 1}`,
      text: 'preview',
    })),
    excluded: excludedType ? [{ type: excludedType, reason: excludedReason }] : [],
    policy: '生成时直接发送这里显示的范围、metrics、evidence；原始大数据不进入 LLM。',
  }))
}

function currentScopePayload(scope = {}) {
  const compact = compactObject(scope, ['center', 'center_coord_type', 'radius_m', 'time_min', 'mode'])
  const polygon = cloneArray(scope.polygon)
  const drawnPolygon = cloneArray(scope.drawn_polygon || scope.drawnPolygon)
  return {
    ...compact,
    has_polygon: polygon.length > 0,
    polygon_point_count: polygon.length,
    has_drawn_polygon: drawnPolygon.length > 0,
    drawn_polygon_point_count: drawnPolygon.length,
    has_isochrone_feature: !!(scope.isochrone_feature || scope.isochroneFeature),
  }
}

function currentEvidenceForSource(context = {}, sourceId = '', sourceTitle = '', readyMetrics = []) {
  const datasets = cloneObject(context.datasets)
  const analysis = cloneObject(context.analysis)
  const evidence = []
  if (readyMetrics.length) {
    evidence.push(createEvidenceItem({
      sourceId,
      sourceTitle,
      type: 'metric_summary',
      title: '标准指标摘要',
      text: readyMetrics.slice(0, 8).map((metric) => `${metric.label}=${metric.value}${metric.unit || ''}`).join('；'),
      payload: { metric_ids: readyMetrics.slice(0, 12).map((metric) => metric.metric_id).filter(Boolean) },
    }))
  }
  if (sourceId === 'current:dataset:poi') {
    const poi = cloneObject(datasets.poi)
    evidence.push(createEvidenceItem({
      sourceId,
      sourceTitle,
      type: 'dataset_summary',
      title: 'POI 基础数据',
      text: `当前来源包含 POI ${Number(poi.count || 0) || 0} 条。完整 POI 明细不传给 AI。`,
      payload: { count: Number(poi.count || 0) || 0 },
    }))
  }
  if (sourceId === 'current:dataset:h3') {
    const h3 = cloneObject(datasets.h3)
    evidence.push(createEvidenceItem({
      sourceId,
      sourceTitle,
      type: 'dataset_summary',
      title: 'H3 / 共享网格',
      text: `当前来源包含 H3 网格 ${Number(h3.count || 0) || 0} 个。完整 geometry/features 不传给 AI。`,
      payload: { count: Number(h3.count || 0) || 0 },
    }))
  }
  const analysisKey = {
    'current:analysis:poi_h3': 'poi_h3',
    'current:analysis:population': 'population',
    'current:analysis:nightlight': 'nightlight',
    'current:analysis:road': 'road',
  }[sourceId]
  if (analysisKey) {
    const item = cloneObject(analysis[analysisKey])
    const summary = analysisKey === 'poi_h3' ? cloneObject(item.summary) : cloneObject(item.summary || item)
    if (Object.keys(summary).length) {
      evidence.push(createEvidenceItem({
        sourceId,
        sourceTitle,
        type: 'analysis_summary',
        title: sourceTitle,
        text: JSON.stringify(summary).slice(0, 700),
        payload: { summary_keys: Object.keys(summary).slice(0, 20) },
      }))
    }
  }
  return evidence
}

function excludedForCurrentSource(context = {}, sourceId = '') {
  const datasets = cloneObject(context.datasets)
  const analysis = cloneObject(context.analysis)
  if (sourceId === 'current:dataset:poi') {
    return [{ type: 'current.datasets.poi.items', reason: '不传原始 POI 列表，只传 POI 数量和轻量摘要。', count: Number((datasets.poi || {}).count || 0) || 0 }]
  }
  if (sourceId === 'current:dataset:h3') {
    return [{ type: 'current.datasets.h3.features', reason: '不传 H3 geometry/features，只传网格数量和轻量摘要。', count: Number((datasets.h3 || {}).count || 0) || 0 }]
  }
  if (sourceId.startsWith('current:analysis:')) {
    const key = sourceId.split(':').pop()
    const item = cloneObject(analysis[key === 'road' ? 'road' : key])
    const featureCount = cloneArray(item.features).length
    return [{ type: `current.analysis.${key}`, reason: '不传完整分析明细/features，只传标准 metrics、缺口和轻量摘要。', count: featureCount }]
  }
  if (sourceId === 'current:scope') {
    return [{ type: 'current.scope.raw_geometry', reason: '不传完整等时圈 GeoJSON，只传范围摘要和点位数量。' }]
  }
  return [{ type: 'current_raw_payload', reason: '不传完整 current，只传该来源已构建的 AI 输入块。' }]
}

export function createPptSystemSources(context = {}) {
  return SYSTEM_SOURCE_DEFINITIONS.map((item) => {
    const ready = getSystemSourceReady(context, item.taskKey)
    const detail = getCurrentSourceDetail(context, item.id, item.taskKey)
    const metrics = cloneArray(((context.metrics || {}).metrics || []))
      .filter((metric) => cloneArray(metric.source_ids || metric.sourceIds).map((sourceId) => asText(sourceId)).includes(item.id))
    const readyMetrics = metrics.filter((metric) => asText(metric.status) === 'ready')
    const gapMetrics = metrics.filter((metric) => asText(metric.status) !== 'ready')
    const scope = ready && item.id === 'current:scope' ? currentScopePayload(context.scope) : null
    const evidence = ready ? currentEvidenceForSource(context, item.id, item.title, readyMetrics) : []
    const aiPayload = createAiPayload({
      sourceId: item.id,
      title: item.title,
      sourceKind: 'system',
      scope,
      metrics: readyMetrics,
      metricGaps: gapMetrics.map((metric, index) => ({
        gap_id: `gap-${index + 1}`,
        metric_id: metric.metric_id,
        source_id: item.id,
        needed_metric: metric.label,
        text: metric.description || `${metric.label || metric.metric_id} 暂无可用数据。`,
        status: metric.status,
      })),
      evidence,
      excluded: excludedForCurrentSource(context, item.id),
      policy: '该来源已构建为 AI 输入块；生成时只发送 scope/metrics/evidence/chart specs，不发送 current 原始数据。',
    })
    return {
      id: item.id,
      type: item.type,
      title: item.title,
      status: ready ? 'ready' : 'pending',
      selected: ready,
      meta: {
        label: detail || (ready ? '已生成' : '待生成'),
        taskKey: item.taskKey,
        sourceKind: 'system',
        readyMetricCount: readyMetrics.length,
        gapMetricCount: gapMetrics.length,
        metrics: metrics.slice(0, 80),
        aiPayload,
        ai_payload: aiPayload,
        transport: createPptTransportFromAiPayload(aiPayload),
      },
    }
  })
}

export function createDefaultUserPptSources() {
  return []
}

export function createDefaultPptSources() {
  return [
    ...createPptSystemSources(),
    ...createDefaultUserPptSources(),
  ]
}

export function createDefaultPptSpec(seed = {}) {
  const selectedSourceIds = cloneArray(seed.sourceIds || seed.source_ids)
    .map((item) => asText(item))
    .filter(Boolean)
  return {
    topic: asText(seed.topic),
    title: asText(seed.title) || 'PPT 指令文件',
    goal: asText(seed.goal) || '形成面向评审的专业策划汇报结构',
    audience: asText(seed.audience) || '政府评审',
    deckType: asText(seed.deckType || seed.deck_type) || '城市更新概念策划',
    pageCount: Number(seed.pageCount ?? seed.page_count ?? DEFAULT_PPT_PAGE_COUNT) || DEFAULT_PPT_PAGE_COUNT,
    style: asText(seed.style) || '专业策划汇报',
    webSourcesEnabled: Object.prototype.hasOwnProperty.call(seed, 'webSourcesEnabled')
      ? !!seed.webSourcesEnabled
      : Object.prototype.hasOwnProperty.call(seed, 'web_sources_enabled')
        ? !!seed.web_sources_enabled
        : true,
    sourceIds: selectedSourceIds,
    outline: cloneArray(seed.outline),
    missingInputs: cloneArray(seed.missingInputs || seed.missing_inputs),
  }
}

export function createDefaultDeckBriefPreview() {
  return {
    status: 'draft',
    slides: [
      {
        id: 'cover',
        index: 1,
        title: '封面',
        purpose: '建立项目命题',
    keyMessage: '明确区域更新的汇报对象与核心命题',
    insight: '',
    evidenceExplanation: [],
    visualPlan: '项目名、区域底图、关键判断一句话',
        requiredSources: ['current:scope'],
      },
      {
        id: 'location',
        index: 2,
        title: '区位判断',
        purpose: '解释区域为什么值得讨论',
        keyMessage: '用交通、周边资源和城市关系建立区位价值',
        insight: '',
        evidenceExplanation: [],
        visualPlan: '区位图、圈层关系、交通节点',
        requiredSources: ['current:scope', 'current:dataset:poi', 'current:dataset:h3'],
      },
      {
        id: 'diagnosis',
        index: 3,
        title: '现状诊断',
        purpose: '把问题说清楚',
        keyMessage: '从 POI、人口、夜光、路网中提炼现状矛盾',
        insight: '',
        evidenceExplanation: [],
        visualPlan: '指标卡、热力图、问题清单',
        requiredSources: ['current:dataset:poi', 'current:analysis:population', 'current:analysis:nightlight', 'current:analysis:road'],
      },
      {
        id: 'strategy',
        index: 4,
        title: '更新策略',
        purpose: '提出空间和功能方向',
        keyMessage: '把诊断转成可讨论的更新策略',
        insight: '',
        evidenceExplanation: [],
        visualPlan: '策略分区、功能组合、空间结构',
        requiredSources: ['current:dataset:h3', 'current:analysis:road'],
      },
      {
        id: 'implementation',
        index: 5,
        title: '实施路径',
        purpose: '形成可推进的行动顺序',
        keyMessage: '用分期、运营和治理路径支撑落地',
        insight: '',
        evidenceExplanation: [],
        visualPlan: '时间轴、责任矩阵、近期行动',
        requiredSources: ['current:scope'],
      },
    ],
  }
}

export function normalizePptSource(seed = {}) {
  const status = asText(seed.status) || 'pending'
  const meta = cloneObject(seed.meta)
  const sourceKind = canonicalPptSourceKind(seed.source_kind || seed.sourceKind || meta.sourceKind, seed.id, seed.type)
  const aiPayload = cloneObject(meta.aiPayload || meta.ai_payload)
  const counts = cloneObject(aiPayload.counts)
  const transport = cloneObject(meta.transport)
  const evidenceNodes = evidenceNodesFromAiPayload(aiPayload)
  const evidenceCount = Number(
    seed.evidence_count
    ?? seed.evidenceCount
    ?? transport.evidence_count
    ?? transport.evidenceCount
    ?? evidenceNodes.length
    ?? counts.evidence
    ?? 0
  ) || 0
  return {
    id: asText(seed.id),
    type: asText(seed.type) || 'source',
    title: asText(seed.title) || '未命名来源',
    status,
    selected: status === 'ready' && !!seed.selected,
    source_kind: sourceKind,
    sourceKind,
    summary: asText(seed.summary || meta.label),
    evidence_count: evidenceCount,
    evidenceCount,
    locator_summary: asText(seed.locator_summary || seed.locatorSummary),
    locatorSummary: asText(seed.locator_summary || seed.locatorSummary),
    availability: asText(seed.availability) || (status === 'ready' ? 'available' : ''),
    meta,
  }
}

export function normalizeDeckSlideBrief(seed = {}, fallbackIndex = 1) {
  const index = Number(seed.index || fallbackIndex) || fallbackIndex
  return {
    id: asText(seed.id) || `slide-${index}`,
    index,
    title: asText(seed.title) || `页面 ${index}`,
    purpose: asText(seed.purpose),
    keyMessage: asText(seed.keyMessage || seed.key_message),
    insight: asText(seed.insight),
    evidenceExplanation: normalizeTextList(seed.evidenceExplanation || seed.evidence_explanation),
    visualPlan: asText(seed.visualPlan || seed.visual_plan),
    requiredSources: cloneArray(seed.requiredSources || seed.required_sources).map((item) => asText(item)).filter(Boolean),
    metricClaims: cloneArray(seed.metricClaims || seed.metric_claims).map((item) => cloneObject(item)).filter((item) => item.metric_id || item.metricId || item.text),
    metricGaps: cloneArray(seed.metricGaps || seed.metric_gaps).map((item) => (item && typeof item === 'object' ? cloneObject(item) : { text: asText(item) })).filter((item) => asText(item.text || item.reason || item.needed_metric || item.neededMetric)),
    visualSpecs: cloneArray(seed.visualSpecs || seed.visual_specs).map((item) => cloneObject(item)).filter((item) => item.visual_id || item.visualId || item.title),
    visualArtifacts: cloneArray(seed.visualArtifacts || seed.visual_artifacts).map((item) => cloneObject(item)).filter((item) => item.visual_id || item.visualId || item.url || item.filename),
  }
}

export function normalizePptOutlineItem(seed = {}, fallbackIndex = 1) {
  const pageNo = Number(seed.pageNo || seed.page_no || fallbackIndex) || fallbackIndex
  return {
    id: asText(seed.id) || `outline-${pageNo}`,
    pageNo,
    theme: asText(seed.theme) || `页面 ${pageNo}`,
    purpose: asText(seed.purpose),
  }
}

export function normalizePptOutline(seed = []) {
  return cloneArray(seed).map((item, index) => normalizePptOutlineItem(item, index + 1))
}

export function normalizeDeckBrief(seed = {}) {
  const slides = cloneArray(seed.slides).length
    ? cloneArray(seed.slides).map((item, index) => normalizeDeckSlideBrief(item, index + 1))
    : []
  return {
    status: asText(seed.status) || 'draft',
    slides,
  }
}

export function normalizeNarrativeSlideRole(seed = {}, fallbackPageNo = 1) {
  const pageNo = Number(seed.pageNo || seed.page_no || fallbackPageNo) || fallbackPageNo
  return {
    pageNo,
    role: asText(seed.role),
    job: asText(seed.job),
    evidenceBucket: asText(seed.evidenceBucket || seed.evidence_bucket),
    visualFamily: asText(seed.visualFamily || seed.visual_family),
    transitionNote: asText(seed.transitionNote || seed.transition_note),
  }
}

export function normalizeNarrativePlan(seed = {}) {
  const roles = cloneArray(seed.slideRoles || seed.slide_roles)
    .map((item, index) => normalizeNarrativeSlideRole(item, index + 1))
    .filter((item) => item.pageNo)
  return {
    storyline: asText(seed.storyline),
    chapters: cloneArray(seed.chapters).map((item) => ({
      name: asText(item && item.name),
      pageRange: asText(item && (item.pageRange || item.page_range)),
      job: asText(item && item.job),
      output: asText(item && item.output),
    })).filter((item) => item.name),
    evidenceBuckets: cloneArray(seed.evidenceBuckets || seed.evidence_buckets).map((item) => ({
      id: asText(item && item.id),
      label: asText(item && item.label),
      allowedSources: cloneArray(item && (item.allowedSources || item.allowed_sources)).map((value) => asText(value)).filter(Boolean),
    })).filter((item) => item.id),
    slideRoles: roles,
    visualRules: (() => {
      const rules = cloneObject(seed.visualRules || seed.visual_rules)
      return {
        spatialFirst: !!(rules.spatialFirst ?? rules.spatial_first),
        numericChartsRequireData: rules.numericChartsRequireData ?? rules.numeric_charts_require_data ?? true,
        diagramForStrategyPages: rules.diagramForStrategyPages ?? rules.diagram_for_strategy_pages ?? true,
        noFallbackBar: rules.noFallbackBar ?? rules.no_fallback_bar ?? true,
      }
    })(),
    missingInputs: cloneArray(seed.missingInputs || seed.missing_inputs).map((item) => asText(item)).filter(Boolean),
  }
}
