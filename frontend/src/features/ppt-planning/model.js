function asText(value, fallback = '') {
  return String(value ?? fallback ?? '').trim()
}

function cloneObject(value, fallback = {}) {
  return value && typeof value === 'object' && !Array.isArray(value) ? { ...value } : { ...fallback }
}

function cloneArray(items) {
  return Array.isArray(items) ? items.map((item) => (item && typeof item === 'object' ? { ...item } : item)) : []
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
  return {
    source_id: asText(sourceId),
    sourceId: asText(sourceId),
    source_title: asText(sourceTitle),
    sourceTitle: asText(sourceTitle),
    type: asText(type),
    title: asText(title),
    text: asText(text),
    payload: cloneObject(payload),
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
  chartSpecs = [],
  excluded = [],
  policy = '',
} = {}) {
  const normalizedScope = scope && typeof scope === 'object' ? cloneObject(scope) : null
  const readyMetrics = cloneArray(metrics).filter((metric) => asText(metric.status) === 'ready')
  const gaps = cloneArray(metricGaps)
  const evidenceItems = cloneArray(evidence).filter((item) => asText(item.title || item.text))
  const charts = cloneArray(chartSpecs).filter((item) => asText(item.chart_id || item.chartId || item.title))
  const included = []
  if (normalizedScope) included.push('scope')
  if (readyMetrics.length) included.push('metrics')
  if (gaps.length) included.push('metric_gaps')
  if (evidenceItems.length) included.push('evidence')
  if (charts.length) included.push('chart_specs')
  return {
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
    evidence: evidenceItems,
    chart_specs: charts,
    chartSpecs: charts,
    excluded: cloneArray(excluded),
    counts: {
      scope: normalizedScope ? 1 : 0,
      metrics: readyMetrics.length,
      metric_gaps: gaps.length,
      evidence: evidenceItems.length,
      chart_specs: charts.length,
    },
    policy: asText(policy) || '生成时只发送这个 AI 输入块；原始大数据不进入 LLM。',
  }
}

export function createPptTransportFromAiPayload(aiPayload = {}) {
  const payload = cloneObject(aiPayload)
  const counts = cloneObject(payload.counts)
  const scopeCount = Number(counts.scope ?? payload.scope_count ?? payload.scopeCount ?? 0) || 0
  const metricCount = Number(counts.metrics ?? payload.metric_count ?? payload.metricCount ?? 0) || 0
  const metricGapCount = Number(counts.metric_gaps ?? counts.metricGaps ?? 0) || 0
  const evidenceCount = Number(counts.evidence ?? payload.evidence_count ?? payload.evidenceCount ?? 0) || 0
  const chartSpecCount = Number(counts.chart_specs ?? counts.chartSpecs ?? 0) || 0
  const included = cloneArray(payload.included)
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
    chart_spec_count: chartSpecCount,
    chartSpecCount,
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
  DIRECTIVE_GENERATING: 'directive_generating',
  DIRECTIVE_DRAFT: 'directive_draft',
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
    researchEnabled: Object.prototype.hasOwnProperty.call(seed, 'researchEnabled')
      ? !!seed.researchEnabled
      : Object.prototype.hasOwnProperty.call(seed, 'research_enabled')
        ? !!seed.research_enabled
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
        visualPlan: '项目名、区域底图、关键判断一句话',
        requiredSources: ['current:scope'],
        speakerNotes: '第一阶段先生成逐页指令，不直接生成 PPTX。',
      },
      {
        id: 'location',
        index: 2,
        title: '区位判断',
        purpose: '解释区域为什么值得讨论',
        keyMessage: '用交通、周边资源和城市关系建立区位价值',
        visualPlan: '区位图、圈层关系、交通节点',
        requiredSources: ['current:scope', 'current:dataset:poi', 'current:dataset:h3'],
        speakerNotes: '后续由 PPT 指令文件决定完整页序。',
      },
      {
        id: 'diagnosis',
        index: 3,
        title: '现状诊断',
        purpose: '把问题说清楚',
        keyMessage: '从 POI、人口、夜光、路网中提炼现状矛盾',
        visualPlan: '指标卡、热力图、问题清单',
        requiredSources: ['current:dataset:poi', 'current:analysis:population', 'current:analysis:nightlight', 'current:analysis:road'],
        speakerNotes: '当前仅展示代表性页面。',
      },
      {
        id: 'strategy',
        index: 4,
        title: '更新策略',
        purpose: '提出空间和功能方向',
        keyMessage: '把诊断转成可讨论的更新策略',
        visualPlan: '策略分区、功能组合、空间结构',
        requiredSources: ['current:dataset:h3', 'current:analysis:road'],
        speakerNotes: '真实生成时会引用选中来源。',
      },
      {
        id: 'implementation',
        index: 5,
        title: '实施路径',
        purpose: '形成可推进的行动顺序',
        keyMessage: '用分期、运营和治理路径支撑落地',
        visualPlan: '时间轴、责任矩阵、近期行动',
        requiredSources: ['current:scope'],
        speakerNotes: 'PPTX 导出在后续阶段接入。',
      },
    ],
  }
}

export function normalizePptSource(seed = {}) {
  const status = asText(seed.status) || 'pending'
  return {
    id: asText(seed.id),
    type: asText(seed.type) || 'file',
    title: asText(seed.title) || '未命名来源',
    status,
    selected: status === 'ready' && !!seed.selected,
    meta: cloneObject(seed.meta),
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
    visualPlan: asText(seed.visualPlan || seed.visual_plan),
    requiredSources: cloneArray(seed.requiredSources || seed.required_sources).map((item) => asText(item)).filter(Boolean),
    speakerNotes: asText(seed.speakerNotes || seed.speaker_notes),
    metricClaims: cloneArray(seed.metricClaims || seed.metric_claims).map((item) => cloneObject(item)).filter((item) => item.metric_id || item.metricId || item.text),
    metricGaps: cloneArray(seed.metricGaps || seed.metric_gaps).map((item) => (item && typeof item === 'object' ? cloneObject(item) : { text: asText(item) })).filter((item) => asText(item.text || item.reason || item.needed_metric || item.neededMetric)),
    chartSpecs: cloneArray(seed.chartSpecs || seed.chart_specs).map((item) => cloneObject(item)).filter((item) => item.chart_id || item.chartId || item.title),
    chartArtifacts: cloneArray(seed.chartArtifacts || seed.chart_artifacts).map((item) => cloneObject(item)).filter((item) => item.chart_id || item.chartId || item.url || item.filename),
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
  const fallback = createDefaultDeckBriefPreview()
  const slides = cloneArray(seed.slides).length
    ? cloneArray(seed.slides).map((item, index) => normalizeDeckSlideBrief(item, index + 1))
    : fallback.slides
  return {
    status: asText(seed.status) || fallback.status,
    slides,
  }
}
