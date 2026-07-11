const text = value => String(value || '').trim()

const REQUIRED_STAGE1_ARTIFACT_IDS = Object.freeze([
  'stage1-report',
  'stage1-evidence-appendix',
  'stage1-design-handoff',
])

const ARTIFACT_TITLES = Object.freeze({
  'stage1-report': '第一阶段策划报告',
  'stage1-evidence-appendix': '证据附录',
  'stage1-design-handoff': '设计交接材料',
})

const ALLOWED_STAGE1_RUN_STATUSES = new Set(['completed', 'completed_with_warnings', 'stale'])

const ARTIFACT_NODE_LIMITS = Object.freeze({
  'stage1-report': 24,
  'stage1-evidence-appendix': 12,
  'stage1-design-handoff': 12,
})

function cloneValue(value) {
  if (Array.isArray(value)) return value.map(cloneValue)
  if (!value || typeof value !== 'object') return value
  return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, cloneValue(item)]))
}

export function normalizeCapabilityInputSelections(value = []) {
  return (Array.isArray(value) ? value : [])
    .map((item) => {
      const requirementId = text(item?.requirement_id || item?.requirementId)
      const mode = text(item?.mode)
      if (!requirementId || !mode) return null
      const normalized = { requirement_id: requirementId, mode }
      const runId = text(item?.run_id || item?.runId)
      if (mode === 'specific_run' && runId) normalized.run_id = runId
      return normalized
    })
    .filter(Boolean)
    .sort((left, right) => left.requirement_id.localeCompare(right.requirement_id))
}

export function capabilityInputSelectionFingerprint(value = []) {
  const normalized = normalizeCapabilityInputSelections(value)
  return normalized.length ? JSON.stringify(normalized) : ''
}

export function capabilitySourceRunId(value = []) {
  const selections = normalizeCapabilityInputSelections(value)
  const approvedReport = selections.find(item => item.requirement_id === 'approved_report')
  return text(approvedReport?.run_id || selections.find(item => item.mode === 'specific_run')?.run_id)
}

export function capabilityRunSourceId(runId = '') {
  const id = text(runId)
  return id ? `package:stage1-run:${id}` : ''
}

export function applyCapabilitySourceSelectionPolicy(state = {}, runId = '', options = {}) {
  const sourceId = capabilityRunSourceId(runId)
  if (!sourceId) return state
  const sources = Array.isArray(state?.sources) ? state.sources : []
  const lockedSourceReady = sources.some(item => (
    text(item?.id) === sourceId && text(item?.status) === 'ready'
  ))
  const additionalSelectedSourceIds = new Set(
    (Array.isArray(options.additionalSelectedSourceIds) ? options.additionalSelectedSourceIds : [])
      .map(text)
      .filter(Boolean),
  )
  const nextSources = sources.map((item) => {
    const id = text(item?.id)
    const ready = text(item?.status) === 'ready'
    const selected = lockedSourceReady && ready && (id === sourceId || additionalSelectedSourceIds.has(id))
    return selected === !!item?.selected ? item : { ...item, selected }
  })
  const selectedSourceIds = nextSources.filter(item => item?.selected).map(item => text(item?.id)).filter(Boolean)
  return {
    ...state,
    sources: nextSources,
    spec: {
      ...(state?.spec || {}),
      sourceIds: selectedSourceIds,
    },
  }
}

function splitBoundedText(value = '', maxLength = 680) {
  const source = text(value)
  if (!source) return []
  const chunks = []
  let remaining = source
  while (remaining.length > maxLength) {
    const candidate = remaining.slice(0, maxLength + 1)
    const breakAt = Math.max(
      candidate.lastIndexOf('\n\n'),
      candidate.lastIndexOf('\n'),
      candidate.lastIndexOf('。'),
      candidate.lastIndexOf('；'),
      candidate.lastIndexOf(' '),
    )
    const cut = breakAt >= Math.floor(maxLength * 0.45) ? breakAt + 1 : maxLength
    chunks.push(remaining.slice(0, cut).trim())
    remaining = remaining.slice(cut).trim()
  }
  if (remaining) chunks.push(remaining)
  return chunks.filter(Boolean)
}

function markdownSections(value = '') {
  const lines = String(value || '').replace(/\r\n/g, '\n').split('\n')
  const sections = []
  let heading = ''
  let content = []
  const flush = () => {
    const body = content.join('\n').trim()
    if (body || heading) sections.push({ heading, body: body || heading })
    content = []
  }
  for (const line of lines) {
    const match = line.match(/^#{1,6}\s+(.+)$/)
    if (match) {
      flush()
      heading = text(match[1])
    } else {
      content.push(line)
    }
  }
  flush()
  return sections.length ? sections : [{ heading: '', body: text(value) }]
}

function structuredSections(value) {
  if (Array.isArray(value)) {
    return value.map((item, index) => ({
      heading: `条目 ${index + 1}`,
      body: typeof item === 'string' ? item : JSON.stringify(item, null, 2),
    }))
  }
  if (value && typeof value === 'object') {
    return Object.entries(value).map(([key, item]) => ({
      heading: key,
      body: typeof item === 'string' ? item : JSON.stringify(item, null, 2),
    }))
  }
  return [{ heading: '', body: text(value) }]
}

function artifactEvidenceNodes(snapshot = {}, sourceId = '', runId = '') {
  const artifact = snapshot?.artifact || {}
  const artifactId = text(artifact.artifact_id)
  const artifactTitle = text(artifact.title) || ARTIFACT_TITLES[artifactId] || artifactId
  const sections = typeof snapshot?.payload === 'string'
    ? markdownSections(snapshot.payload)
    : structuredSections(snapshot?.payload)
  const limit = ARTIFACT_NODE_LIMITS[artifactId] || 8
  const nodes = []
  for (const section of sections) {
    for (const chunk of splitBoundedText(section.body)) {
      if (nodes.length >= limit) return nodes
      const index = nodes.length + 1
      nodes.push({
        id: `${sourceId}:${artifactId}:${index}`,
        source_id: sourceId,
        source_type: 'package',
        title: section.heading ? `${artifactTitle} · ${section.heading}` : artifactTitle,
        content: chunk,
        summary: chunk.slice(0, 260),
        locator: `${artifactId} · 片段 ${index}`,
        evidence_level: 'approved_analysis_artifact',
        citation: `${runId}/${artifactId}`,
        metadata: {
          run_id: runId,
          source_run_id: text(artifact.source_run_id) || runId,
          artifact_id: artifactId,
          content_digest: text(artifact.content_digest),
          artifact_version: text(artifact.version),
        },
      })
    }
  }
  return nodes
}

function validateStage1RunDetail(detail = {}, expectedRunId = '') {
  const run = detail?.run || {}
  const runId = text(run.run_id)
  if (!runId || runId !== text(expectedRunId)) throw new Error('capability_run_identity_mismatch')
  if (text(run.capability_id) !== 'urban-strategy-stage1') throw new Error('capability_run_is_not_stage1')
  if (!ALLOWED_STAGE1_RUN_STATUSES.has(text(run.status))) throw new Error(`capability_run_not_consumable:${text(run.status) || 'unknown'}`)
  const snapshots = (Array.isArray(detail?.artifacts) ? detail.artifacts : [])
    .filter(item => item?.direction === 'output')
  const byId = new Map(snapshots.map(item => [text(item?.artifact?.artifact_id), item]))
  const missing = REQUIRED_STAGE1_ARTIFACT_IDS.filter((artifactId) => {
    const snapshot = byId.get(artifactId)
    return !snapshot || snapshot.payload === null || snapshot.payload === undefined || snapshot.payload === ''
  })
  if (missing.length) throw new Error(`capability_run_artifacts_missing:${missing.join(',')}`)
  return { run, snapshots: REQUIRED_STAGE1_ARTIFACT_IDS.map(id => byId.get(id)) }
}

export function createStage1CapabilityPlaceholderSource(runId = '') {
  const id = text(runId)
  return {
    id: capabilityRunSourceId(id),
    type: 'package',
    title: `Stage 1 审定成果 · ${id}`,
    status: 'generating',
    selected: false,
    source_kind: 'package',
    summary: '正在读取锁定 Capability Run 的不可变成果快照。',
    availability: 'building',
    meta: {
      label: '正在读取不可变版本',
      sourceKind: 'package',
      immutable: true,
      capabilityRunId: id,
    },
  }
}

export function createStage1CapabilityFailedSource(runId = '', error = null) {
  const id = text(runId)
  const message = text(error instanceof Error ? error.message : error) || '读取不可变 Capability Run 失败'
  return {
    ...createStage1CapabilityPlaceholderSource(id),
    status: 'failed',
    summary: `无法读取锁定版本：${message}`,
    availability: 'unavailable',
    meta: {
      ...createStage1CapabilityPlaceholderSource(id).meta,
      label: '锁定版本读取失败',
      error: message,
    },
  }
}

export function createStage1CapabilityPptSource(detail = {}, expectedRunId = '') {
  const { run, snapshots } = validateStage1RunDetail(detail, expectedRunId)
  const runId = text(run.run_id)
  const sourceId = capabilityRunSourceId(runId)
  const evidenceNodes = snapshots.flatMap(snapshot => artifactEvidenceNodes(snapshot, sourceId, runId)).slice(0, 48)
  if (!evidenceNodes.length) throw new Error('capability_run_has_no_ppt_evidence')
  const aiPayload = {
    version: 'ppt_ai_input_block_v1',
    source_id: sourceId,
    title: `Stage 1 审定成果 · ${runId}`,
    source_kind: 'package',
    included: ['evidence'],
    scope: null,
    metrics: [],
    metric_gaps: [],
    evidence_nodes: evidenceNodes,
    counts: {
      scope: 0,
      metrics: 0,
      metric_gaps: 0,
      evidence: evidenceNodes.length,
      visual_specs: 0,
    },
    policy: '仅使用已锁定 Capability Run 的不可变 Stage 1 报告、证据附录和设计交接成果；不回退到当前运行时文件。',
  }
  return {
    id: sourceId,
    type: 'package',
    title: aiPayload.title,
    status: 'ready',
    selected: true,
    source_kind: 'package',
    summary: `已锁定 ${runId}，包含 ${evidenceNodes.length} 个可审计证据片段。`,
    evidence_count: evidenceNodes.length,
    availability: 'available',
    locator_summary: `Capability Run ${runId}`,
    meta: {
      label: '不可变 Stage 1 成果',
      sourceKind: 'package',
      immutable: true,
      capabilityRunId: runId,
      capabilityId: text(run.capability_id),
      completedAt: text(run.completed_at),
      artifactIds: cloneValue(REQUIRED_STAGE1_ARTIFACT_IDS),
      aiPayload,
      ai_payload: aiPayload,
    },
  }
}

export { REQUIRED_STAGE1_ARTIFACT_IDS }
