export const PPT_LAUNCHER_CAPABILITY_IDS = Object.freeze([
  'ppt-planning',
  'spatial-programming-matrix',
])

const STATUS_LABELS = Object.freeze({
  ready: '可运行',
  limited: '有条件可运行',
  blocked: '缺少输入',
  running: '正在运行',
  completed: '已有结果',
  stale: '结果已过期',
  failed: '运行失败',
  unavailable: '不可执行',
  checking: '检查中',
})

const CARD_META = Object.freeze({
  'ppt-planning': { shortLabel: 'PPT', accent: 'presentation', actionLabel: '打开 PPT 工作台' },
  'spatial-programming-matrix': { shortLabel: '矩阵', accent: 'planning', actionLabel: '配置空间决策矩阵' },
})

export function capabilityLauncherStatusLabel(state = '') {
  return STATUS_LABELS[String(state || '')] || '待检查'
}

export function buildPptCapabilityLauncherCards(capabilities = [], overview = {}) {
  const capabilitiesById = new Map((Array.isArray(capabilities) ? capabilities : [])
    .map((capability) => [String(capability?.id || ''), capability]))
  const overviewById = new Map((Array.isArray(overview?.cards) ? overview.cards : [])
    .map((card) => [String(card?.capability_id || ''), card]))

  return PPT_LAUNCHER_CAPABILITY_IDS.map((id) => {
    const capability = capabilitiesById.get(id)
    if (!capability) return null
    const overviewCard = overviewById.get(id)
    const state = String(overviewCard?.state || (capability.status === 'available' ? 'checking' : 'unavailable'))
    return {
      id,
      title: String(capability.display_name || id),
      description: String(capability.description || ''),
      state,
      statusLabel: capabilityLauncherStatusLabel(state),
      outputs: (Array.isArray(capability.output_contract) ? capability.output_contract : []).slice(0, 3),
      ...CARD_META[id],
    }
  }).filter(Boolean)
}
