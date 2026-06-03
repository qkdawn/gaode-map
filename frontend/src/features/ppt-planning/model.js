function asText(value, fallback = '') {
  return String(value ?? fallback ?? '').trim()
}

function cloneObject(value, fallback = {}) {
  return value && typeof value === 'object' && !Array.isArray(value) ? { ...value } : { ...fallback }
}

function cloneArray(items) {
  return Array.isArray(items) ? items.map((item) => (item && typeof item === 'object' ? { ...item } : item)) : []
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
    id: 'system:scope',
    type: 'data',
    title: '当前等时圈范围',
    label: '空间范围',
    taskKey: 'scope',
  },
  {
    id: 'system:poi',
    type: 'data',
    title: 'POI 基础数据',
    label: '系统数据',
    taskKey: 'poi_fetch',
  },
  {
    id: 'system:h3',
    type: 'sheet',
    title: 'H3 / 共享网格',
    label: '空间网格',
    taskKey: 'poi_h3_grid',
  },
  {
    id: 'system:population',
    type: 'data',
    title: '人口结构分析',
    label: '系统数据',
    taskKey: 'population',
  },
  {
    id: 'system:nightlight',
    type: 'data',
    title: '夜光强度分析',
    label: '系统数据',
    taskKey: 'nightlight',
  },
  {
    id: 'system:road-syntax',
    type: 'data',
    title: '路网与可达性分析',
    label: '系统数据',
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

export function createPptSystemSources(context = {}) {
  return SYSTEM_SOURCE_DEFINITIONS.map((item) => {
    const ready = getSystemSourceReady(context, item.taskKey)
    const detail = getSourceDetail(context, item.taskKey)
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
        requiredSources: ['system:scope'],
        speakerNotes: '第一阶段先生成逐页指令，不直接生成 PPTX。',
      },
      {
        id: 'location',
        index: 2,
        title: '区位判断',
        purpose: '解释区域为什么值得讨论',
        keyMessage: '用交通、周边资源和城市关系建立区位价值',
        visualPlan: '区位图、圈层关系、交通节点',
        requiredSources: ['system:scope', 'system:poi', 'system:h3'],
        speakerNotes: '后续由 PPT 指令文件决定完整页序。',
      },
      {
        id: 'diagnosis',
        index: 3,
        title: '现状诊断',
        purpose: '把问题说清楚',
        keyMessage: '从 POI、人口、夜光、路网中提炼现状矛盾',
        visualPlan: '指标卡、热力图、问题清单',
        requiredSources: ['system:poi', 'system:population', 'system:nightlight', 'system:road-syntax'],
        speakerNotes: '当前仅展示代表性页面。',
      },
      {
        id: 'strategy',
        index: 4,
        title: '更新策略',
        purpose: '提出空间和功能方向',
        keyMessage: '把诊断转成可讨论的更新策略',
        visualPlan: '策略分区、功能组合、空间结构',
        requiredSources: ['system:h3', 'system:road-syntax'],
        speakerNotes: '真实生成时会引用选中来源。',
      },
      {
        id: 'implementation',
        index: 5,
        title: '实施路径',
        purpose: '形成可推进的行动顺序',
        keyMessage: '用分期、运营和治理路径支撑落地',
        visualPlan: '时间轴、责任矩阵、近期行动',
        requiredSources: ['system:scope'],
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
