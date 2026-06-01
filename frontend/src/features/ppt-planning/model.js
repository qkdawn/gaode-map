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

export function createDefaultPptSources() {
  return [
    {
      id: 'summary',
      type: 'report',
      title: '区域总结.md',
      status: 'ready',
      selected: true,
      meta: { label: '当前报告' },
    },
    {
      id: 'scope',
      type: 'data',
      title: '当前地图范围.json',
      status: 'ready',
      selected: true,
      meta: { label: '空间范围' },
    },
    {
      id: 'evidence',
      type: 'sheet',
      title: 'POI 人口 夜光 路网证据.xlsx',
      status: 'ready',
      selected: true,
      meta: { label: '分析指标' },
    },
    {
      id: 'attachment',
      type: 'file',
      title: '附件素材待接入.pptx',
      status: 'pending',
      selected: false,
      meta: { label: '待接入' },
    },
    {
      id: 'web-research',
      type: 'web',
      title: '联网来源待研究.url',
      status: 'pending',
      selected: false,
      meta: { label: '待研究' },
    },
  ]
}

export function createDefaultPptSpec(seed = {}) {
  const selectedSourceIds = cloneArray(seed.sourceIds || seed.source_ids)
    .map((item) => asText(item))
    .filter(Boolean)
  return {
    topic: asText(seed.topic),
    title: asText(seed.title) || 'PPT Spec',
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
        requiredSources: ['summary', 'scope'],
        speakerNotes: '第一阶段先生成 page brief，不直接生成 PPTX。',
      },
      {
        id: 'location',
        index: 2,
        title: '区位判断',
        purpose: '解释区域为什么值得讨论',
        keyMessage: '用交通、周边资源和城市关系建立区位价值',
        visualPlan: '区位图、圈层关系、交通节点',
        requiredSources: ['scope', 'evidence'],
        speakerNotes: '后续由 PPT Spec 决定完整页序。',
      },
      {
        id: 'diagnosis',
        index: 3,
        title: '现状诊断',
        purpose: '把问题说清楚',
        keyMessage: '从 POI、人口、夜光、路网中提炼现状矛盾',
        visualPlan: '指标卡、热力图、问题清单',
        requiredSources: ['evidence'],
        speakerNotes: '当前仅展示代表性页面。',
      },
      {
        id: 'strategy',
        index: 4,
        title: '更新策略',
        purpose: '提出空间和功能方向',
        keyMessage: '把诊断转成可讨论的更新策略',
        visualPlan: '策略分区、功能组合、空间结构',
        requiredSources: ['summary', 'evidence'],
        speakerNotes: '真实生成时会引用选中来源。',
      },
      {
        id: 'implementation',
        index: 5,
        title: '实施路径',
        purpose: '形成可推进的行动顺序',
        keyMessage: '用分期、运营和治理路径支撑落地',
        visualPlan: '时间轴、责任矩阵、近期行动',
        requiredSources: ['summary'],
        speakerNotes: 'PPTX 导出在后续阶段接入。',
      },
    ],
  }
}

export function normalizePptSource(seed = {}) {
  return {
    id: asText(seed.id),
    type: asText(seed.type) || 'file',
    title: asText(seed.title) || '未命名来源',
    status: asText(seed.status) || 'pending',
    selected: !!seed.selected,
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
