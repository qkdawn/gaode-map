import {
  asText,
  clampText,
  cloneArray,
  cloneAgentSessionRecord,
  cloneObject,
  consumeSseStream,
  normalizeAgentPanelPreloadNotes,
  normalizeAgentToolSummary,
  sortAgentSessions,
} from './normalizers.js'
import {
  buildAnalysisTaskConfirmation,
  cloneAnalysisTaskConfirmation,
  focusAnalysisTaskPanel,
  getAnalysisTaskDefinition,
  getAnalysisTaskDefinitions,
  runAnalysisTask,
} from './analysis-task-registry.js'
import { buildAnalysisTaskParamBundle } from './analysis-task-params.js'
import { createAgentPptPlanningTabMethods } from './ppt-planning-tabs.js'
import {
  normalizeAgentPptPlanningTab,
  serializeAgentPptPlanningTab,
} from './ppt-planning-tabs.js'

export function createAgentBasisDrawerMethods() {
  return {
    openBasisDrawer(payload = null, event = null) {
      if (event && typeof event.stopPropagation === 'function') event.stopPropagation()
      this.basisDrawerPayload = this.normalizeBasisPayload(payload)
      this.basisDrawerActiveTab = 'basic'
      this.basisPromptEditMode = false
      this.basisPromptError = ''
      this.basisPromptNotice = ''
      this.basisDrawerOpen = true
      if (this.basisDrawerPayload.promptKey && !asText(this.basisDrawerPayload.promptSnapshot && this.basisDrawerPayload.promptSnapshot.prompt_key)) {
        this.ensureAgentPromptConfig(this.basisDrawerPayload.promptKey)
          .then((config) => {
            if (!config || !this.basisDrawerOpen) return
            const current = this.normalizeBasisPayload(this.basisDrawerPayload)
            if (asText(current.promptSnapshot && current.promptSnapshot.prompt_key)) return
            this.basisDrawerPayload = this.normalizeBasisPayload({
              ...current,
              promptSnapshot: config,
              promptSourceLabel: '当前配置，非历史快照',
              aiPrompt: config.system_prompt,
              aiPromptPayloadNote: config.payload_note,
              outputSchema: config.output_schema,
            })
          })
          .catch(() => {})
      }
    },
    closeBasisDrawer() {
      this.basisDrawerOpen = false
      this.basisDrawerPayload = null
      this.basisDrawerActiveTab = 'basic'
      this.basisPromptEditMode = false
      this.basisPromptError = ''
      this.basisPromptNotice = ''
    },
    setBasisDrawerTab(tab = 'basic') {
      const key = asText(tab) || 'basic'
      if (!this.getBasisDrawerTabs().some((item) => item.key === key)) return
      this.basisDrawerActiveTab = key
    },
    getBasisDrawerTabs() {
      return [
        { key: 'basic', label: '基础说明' },
        { key: 'validation', label: '输出验证' },
        { key: 'template', label: '规则模板' },
        { key: 'raw', label: '原始字段' },
      ]
    },
    getBasisDrawerPayload() {
      return this.normalizeBasisPayload(this.basisDrawerPayload || {})
    },
    normalizeBasisPayload(payload = null) {
      const source = payload && typeof payload === 'object' ? payload : {}
      const sourceType = asText(source.sourceType || source.source_type || 'rule')
      const defaultPrompt = sourceType === 'rule'
        ? ''
        : '当前结果没有可追溯的 AI prompt。'
      return {
        title: asText(source.title) || '生成依据',
        currentConclusion: asText(source.currentConclusion || source.current_conclusion),
        fields: cloneArray(source.fields).filter((item) => item && (asText(item.label) || asText(item.key))),
        rules: cloneArray(source.rules).map((item) => asText(item)).filter(Boolean),
        template: asText(source.template),
        aiPrompt: asText(source.aiPrompt || source.ai_prompt) || defaultPrompt,
        aiPromptPayloadNote: asText(source.aiPromptPayloadNote || source.ai_prompt_payload_note),
        outputSchema: cloneObject(source.outputSchema || source.output_schema || {}),
        promptKey: asText(source.promptKey || source.prompt_key),
        promptSnapshot: cloneObject(source.promptSnapshot || source.prompt_snapshot || {}),
        promptSourceLabel: asText(source.promptSourceLabel || source.prompt_source_label),
        rawInput: cloneObject(source.rawInput || source.raw_input || {}),
        validationResults: cloneObject(source.validationResults || source.validation_results || {}),
        sourceType,
      }
    },
    normalizeAgentPromptConfig(seed = null) {
      const source = seed && typeof seed === 'object' ? seed : {}
      return {
        prompt_key: asText(source.prompt_key || source.promptKey),
        title: asText(source.title),
        system_prompt: asText(source.system_prompt || source.systemPrompt),
        payload_note: asText(source.payload_note || source.payloadNote),
        output_schema: cloneObject(source.output_schema || source.outputSchema || {}),
        evidence_version: asText(source.evidence_version || source.evidenceVersion),
        updated_at: asText(source.updated_at || source.updatedAt),
      }
    },
    async ensureAgentPromptConfig(promptKey = '', force = false) {
      const key = asText(promptKey)
      if (!key) return null
      if (!force && this.agentPromptConfigs && this.agentPromptConfigs[key]) {
        return this.normalizeAgentPromptConfig(this.agentPromptConfigs[key])
      }
      const res = await fetch(`/api/v1/analysis/agent/prompts/${encodeURIComponent(key)}`)
      if (!res.ok) throw new Error(`提示词配置读取失败(${res.status})`)
      const config = this.normalizeAgentPromptConfig(await res.json())
      this.agentPromptConfigs = { ...cloneObject(this.agentPromptConfigs), [key]: config }
      return config
    },
    getBasisPromptEffectiveConfig() {
      const payload = this.getBasisDrawerPayload()
      const snapshot = this.normalizeAgentPromptConfig(payload.promptSnapshot)
      if (snapshot.prompt_key) return snapshot
      const current = this.normalizeAgentPromptConfig((this.agentPromptConfigs || {})[payload.promptKey])
      return current.prompt_key ? current : { prompt_key: payload.promptKey }
    },
    getPromptMissingMessage(promptKey = '') {
      const key = asText(promptKey)
      if (!key) return '当前结果没有可追溯的 AI prompt。'
      return `当前结果没有本次 AI 调用 prompt 快照；可读取当前 Prompt Registry 配置，但这不是历史调用证据。prompt_key: ${key}`
    },
    resolveBasisPromptDisplay(promptKey = '', promptSnapshotSeed = null) {
      const key = asText(promptKey)
      const snapshot = this.normalizeAgentPromptConfig(promptSnapshotSeed)
      if (snapshot.prompt_key && snapshot.system_prompt) {
        return {
          aiPrompt: snapshot.system_prompt,
          aiPromptPayloadNote: snapshot.payload_note,
          outputSchema: cloneObject(snapshot.output_schema),
          promptSnapshot: snapshot,
          promptSourceLabel: '本次生成实际使用的提示词快照',
        }
      }
      const current = this.normalizeAgentPromptConfig((this.agentPromptConfigs || {})[key])
      if (current.prompt_key && current.system_prompt) {
        return {
          aiPrompt: current.system_prompt,
          aiPromptPayloadNote: current.payload_note,
          outputSchema: cloneObject(current.output_schema),
          promptSnapshot: current,
          promptSourceLabel: '当前配置，非历史快照',
        }
      }
      return {
        aiPrompt: this.getPromptMissingMessage(key),
        aiPromptPayloadNote: '',
        outputSchema: {},
        promptSnapshot: snapshot.prompt_key ? snapshot : {},
        promptSourceLabel: key ? '无本次调用快照' : '无可追溯提示词',
      }
    },
    startBasisPromptEdit() {
      const config = this.getBasisPromptEffectiveConfig()
      this.basisPromptDraft = {
        system_prompt: asText(config.system_prompt),
        payload_note: asText(config.payload_note),
        output_schema_text: this.formatBasisRawInput(config.output_schema),
      }
      this.basisPromptEditMode = true
      this.basisPromptError = ''
      this.basisPromptNotice = ''
    },
    cancelBasisPromptEdit() {
      this.basisPromptEditMode = false
      this.basisPromptError = ''
    },
    async saveBasisPromptConfig() {
      const payload = this.getBasisDrawerPayload()
      const key = asText(payload.promptKey)
      if (!key) return
      let outputSchema = {}
      try {
        outputSchema = JSON.parse(asText(this.basisPromptDraft.output_schema_text) || '{}')
      } catch (_) {
        this.basisPromptError = 'output_schema 必须是合法 JSON'
        return
      }
      this.basisPromptSaving = true
      this.basisPromptError = ''
      try {
        const res = await fetch(`/api/v1/analysis/agent/prompts/${encodeURIComponent(key)}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            system_prompt: asText(this.basisPromptDraft.system_prompt),
            payload_note: asText(this.basisPromptDraft.payload_note),
            output_schema: outputSchema,
          }),
        })
        if (!res.ok) {
          let detail = ''
          try { detail = await res.text() } catch (_) {}
          throw new Error(detail || `提示词保存失败(${res.status})`)
        }
        const config = this.normalizeAgentPromptConfig(await res.json())
        this.agentPromptConfigs = { ...cloneObject(this.agentPromptConfigs), [key]: config }
        this.basisPromptEditMode = false
        this.basisPromptNotice = '已保存。下一次生成生效，当前历史结果不重算。'
        if (!asText(payload.promptSnapshot && payload.promptSnapshot.prompt_key)) {
          this.basisDrawerPayload = this.normalizeBasisPayload({
            ...payload,
            promptSnapshot: config,
            promptSourceLabel: '当前配置，非历史快照',
            aiPrompt: config.system_prompt,
            aiPromptPayloadNote: config.payload_note,
            outputSchema: config.output_schema,
          })
        }
      } catch (err) {
        this.basisPromptError = asText(err && err.message) || String(err)
      } finally {
        this.basisPromptSaving = false
      }
    },
    formatBasisFieldValue(value) {
      if (value === undefined || value === null || value === '') return '-'
      if (Array.isArray(value)) {
        return value.map((item) => {
          if (item && typeof item === 'object') {
            const label = asText(item.label || item.name || item.key || item.title)
            const itemValue = item.value ?? item.count ?? item.delta ?? item.poi_count ?? ''
            if (label && itemValue !== '') return `${label}：${this.formatBasisFieldValue(itemValue)}`
            const compactParts = [
              asText(item.name),
              asText(item.parent),
              item.delta !== undefined && item.delta !== null ? `变化 ${item.delta}` : '',
              item.last_count !== undefined && item.last_count !== null ? `末年 ${item.last_count}` : '',
              item.poi_count !== undefined && item.poi_count !== null ? `${item.poi_count}点` : '',
            ].filter(Boolean)
            return compactParts.join('，') || JSON.stringify(item)
          }
          return asText(item)
        }).filter(Boolean).join('；') || '-'
      }
      if (typeof value === 'object') {
        const entries = Object.entries(value)
          .filter(([, itemValue]) => itemValue !== undefined && itemValue !== null && itemValue !== '')
          .slice(0, 8)
          .map(([key, itemValue]) => `${key}：${this.formatBasisFieldValue(itemValue)}`)
        return entries.join('；') || '-'
      }
      return asText(value)
    },
    formatBasisRawInput(value = null) {
      const raw = value && typeof value === 'object' ? value : {}
      try {
        return JSON.stringify(raw, null, 2)
      } catch (_) {
        return '{}'
      }
    },
    getAgentIterationPoiSystemPrompt() {
      return this.getPromptMissingMessage('poi_iteration')
    },
    getAgentIterationPoiPromptPayloadNote() {
      return ''
    },
    hasBasisFieldValue(value) {
      if (value === undefined || value === null || value === '') return false
      if (Array.isArray(value)) return value.length > 0
      if (typeof value === 'object') return Object.keys(value).length > 0
      return true
    },
    formatBasisRatio(value) {
      const number = Number(value)
      if (!Number.isFinite(number)) return ''
      return `${(number * 100).toFixed(1)}%`
    },
    summarizeRoadOrientationAnalysis(analysis = null) {
      const source = analysis && typeof analysis === 'object' ? analysis : {}
      const dominant = asText(source.dominant_orientation)
      const secondary = asText(source.secondary_orientation)
      const dominantShare = this.formatBasisRatio(source.dominant_share)
      const secondaryShare = this.formatBasisRatio(source.secondary_share)
      const parts = []
      if (dominant) parts.push(`主导：${dominant}${dominantShare ? `（${dominantShare}）` : ''}`)
      if (secondary) parts.push(`次主导：${secondary}${secondaryShare ? `（${secondaryShare}）` : ''}`)
      const rows = cloneArray(source.orientation_rows)
        .map((item) => {
          const label = asText(item && item.label)
          const share = this.formatBasisRatio(item && item.length_share)
          return label && share ? `${label} ${share}` : ''
        })
        .filter(Boolean)
        .slice(0, 4)
      if (rows.length) parts.push(`分布：${rows.join('、')}`)
      return parts.join('；') || ''
    },
    appendBasisField(fields, key, label, value) {
      if (!Array.isArray(fields) || !this.hasBasisFieldValue(value)) return
      fields.push({ key, label, value })
    },
    buildAgentSummaryEvidencePack(panelPayloads = null) {
      const payloads = panelPayloads && typeof panelPayloads === 'object'
        ? cloneObject(panelPayloads)
        : this.getAgentActiveSummaryPanelPayloads()
      const pack = this.getAgentSummaryPack(payloads)
      const businessProfile = cloneObject(payloads.current_business_profile || {})
      const poiStructure = cloneObject(payloads.current_poi_structure_analysis || {})
      const h3Structure = cloneObject(payloads.current_h3_structure_analysis || {})
      const commercialHotspots = cloneObject(payloads.current_commercial_hotspots || {})
      const populationProfile = cloneObject(payloads.current_population_profile_analysis || {})
      const nightlightPattern = cloneObject(
        payloads.current_nightlight_pattern_analysis
        || payloads.nightlight_pattern
        || payloads.nightlight
        || {},
      )
      const nightlightSummary = cloneObject(
        payloads.current_nightlight_summary
        || ((payloads.nightlight_overview || {}).summary)
        || ((this.nightlightOverview || {}).summary)
        || {},
      )
      const roadPattern = cloneObject(payloads.current_road_pattern_analysis || {})
      const roadSummary = cloneObject(
        payloads.road_syntax_summary
        || ((payloads.road || {}).summary)
        || this.roadSyntaxSummary
        || {},
      )
      const areaFacts = cloneObject(payloads.current_area_character_facts || {})
      return {
        task: 'summary_pack_generation',
        evidence_version: 'summary_pack_v1',
        generated_sections: {
          headline_judgment: cloneObject(pack.headline_judgment || {}),
          user_profile: cloneObject(pack.user_profile || {}),
          behavior_inference: cloneObject(pack.behavior_inference || {}),
          tourism_cross_analysis: cloneObject(pack.tourism_cross_analysis || {}),
        },
        business_profile: {
          label: businessProfile.business_profile,
          portrait: businessProfile.portrait,
          summary_text: businessProfile.summary_text,
          functional_mix_score: businessProfile.functional_mix_score,
        },
        poi_structure: {
          summary_text: poiStructure.summary_text,
          dominant_categories: cloneArray(poiStructure.dominant_categories),
          structure_tags: cloneArray(poiStructure.structure_tags),
          top_category_mix: cloneArray(poiStructure.top_category_mix || poiStructure.top_categories),
        },
        spatial_structure: {
          distribution_pattern: h3Structure.distribution_pattern,
          summary_text: h3Structure.summary_text,
          hotspot_mode: commercialHotspots.hotspot_mode || h3Structure.hotspot_mode,
          hotspot_summary: commercialHotspots.summary_text,
          core_zone_count: commercialHotspots.core_zone_count ?? h3Structure.core_zone_count,
          opportunity_zone_count: commercialHotspots.opportunity_zone_count ?? h3Structure.opportunity_count,
          hotspot_count: h3Structure.hotspot_count,
          structure_signal_count: h3Structure.structure_signal_count,
        },
        population_profile: {
          summary_text: populationProfile.summary_text,
          total_population: populationProfile.total_population,
          top_age_band: populationProfile.top_age_band,
          dominant_age_band: populationProfile.dominant_age_band,
        },
        nightlight_pattern: {
          total_radiance: nightlightPattern.total_radiance ?? nightlightSummary.total_radiance,
          mean_radiance: nightlightPattern.mean_radiance ?? nightlightSummary.mean_radiance,
          p90_radiance: nightlightPattern.p90_radiance ?? nightlightSummary.p90_radiance,
          peak_radiance: nightlightPattern.peak_radiance ?? nightlightSummary.peak_radiance,
          lit_pixel_ratio: nightlightPattern.lit_pixel_ratio ?? nightlightSummary.lit_pixel_ratio,
          valid_pixel_count: nightlightPattern.valid_pixel_count ?? nightlightSummary.valid_pixel_count,
          peak_to_edge_ratio: nightlightPattern.peak_to_edge_ratio ?? nightlightSummary.peak_to_edge_ratio,
          sector_direction_analysis: cloneObject(nightlightPattern.sector_direction_analysis || nightlightSummary.sector_direction_analysis || {}),
        },
        road_pattern: {
          summary_text: roadPattern.summary_text || roadSummary.summary_text,
          connectivity_signal: roadPattern.connectivity_signal || roadSummary.connectivity_signal,
          access_signal: roadPattern.access_signal || roadSummary.access_signal,
          readability_signal: roadPattern.readability_signal || roadSummary.readability_signal,
          road_orientation_analysis: cloneObject(roadPattern.road_orientation_analysis || roadSummary.road_orientation_analysis || {}),
        },
        area_facts: areaFacts,
      }
    },
    getAgentSummarySectionPrompt(sectionKey = '') {
      return this.getPromptMissingMessage(sectionKey)
    },
    getAgentSummaryPromptPayloadNote(sectionKey = '') {
      return ''
    },
    buildAgentSummaryEvidenceFields(section = {}, evidence = {}) {
      const key = asText(section.sectionKey || section.section_key)
      const generated = evidence.generated_sections || {}
      const fields = cloneArray(section.dimensions).map((dimension) => ({
        key: asText(dimension.key),
        label: asText(dimension.label),
        value: asText(dimension.conclusion),
      }))
      this.appendBasisField(fields, 'evidence_version', '证据包版本', evidence.evidence_version)
      this.appendBasisField(fields, 'task', '生成任务', evidence.task)
      const headline = generated.headline_judgment || {}
      const userProfile = generated.user_profile || {}
      const behavior = generated.behavior_inference || {}
      const tourismCrossAnalysis = generated.tourism_cross_analysis || {}
      if (key === 'headline') {
      this.appendBasisField(fields, 'headline_summary', '核心判断', headline.summary)
        this.appendBasisField(fields, 'supporting_clause', '支撑解释', headline.supporting_clause)
      }
      if (key === 'user_profile') {
        this.appendBasisField(fields, 'user_profile_headline', '用户画像结论', userProfile.headline)
        this.appendBasisField(fields, 'user_profile_traits', '画像特征', userProfile.traits)
      }
      if (key === 'behavior_inference') {
        this.appendBasisField(fields, 'behavior_headline', '行为推断结论', behavior.headline)
        this.appendBasisField(fields, 'behavior_traits', '行为特征', behavior.traits)
      }
      if (key === 'tourism_cross_analysis') {
        this.appendBasisField(fields, 'tourism_cross_analysis_title', '分析标题', tourismCrossAnalysis.title)
        this.appendBasisField(fields, 'tourism_cross_analysis_content', '交叉分析文本', tourismCrossAnalysis.content)
      }
      if (key === 'headline' || key === 'poi_structure' || key === 'business_support' || key === 'tourism_cross_analysis') {
        this.appendBasisField(fields, 'business_profile', '商业画像', evidence.business_profile)
        this.appendBasisField(fields, 'poi_structure_summary', 'POI 结构摘要', (evidence.poi_structure || {}).summary_text)
        this.appendBasisField(fields, 'dominant_categories', '主导业态', (evidence.poi_structure || {}).dominant_categories)
        this.appendBasisField(fields, 'structure_tags', '结构标签', (evidence.poi_structure || {}).structure_tags)
      }
      if (key === 'headline' || key === 'spatial_structure' || key === 'tourism_cross_analysis') {
        this.appendBasisField(fields, 'spatial_structure_summary', '空间结构摘要', (evidence.spatial_structure || {}).summary_text)
        this.appendBasisField(fields, 'hotspot_mode', '热点模式', (evidence.spatial_structure || {}).hotspot_mode)
        this.appendBasisField(fields, 'core_zone_count', '核心区数量', (evidence.spatial_structure || {}).core_zone_count)
        this.appendBasisField(fields, 'opportunity_zone_count', '机会区数量', (evidence.spatial_structure || {}).opportunity_zone_count)
      }
      if (key === 'headline' || key === 'user_profile' || key === 'behavior_inference' || key === 'tourism_cross_analysis') {
        this.appendBasisField(fields, 'population_profile', '人口画像摘要', (evidence.population_profile || {}).summary_text)
        this.appendBasisField(fields, 'top_age_band', '主要年龄段', (evidence.population_profile || {}).top_age_band || (evidence.population_profile || {}).dominant_age_band)
      }
      if (key === 'headline' || key === 'consumption_vitality' || key === 'behavior_inference' || key === 'business_support' || key === 'tourism_cross_analysis') {
        const nightlight = evidence.nightlight_pattern || {}
        const road = evidence.road_pattern || {}
        this.appendBasisField(fields, 'total_radiance', '总辐亮', nightlight.total_radiance)
        this.appendBasisField(fields, 'mean_radiance', '平均辐亮', nightlight.mean_radiance)
        this.appendBasisField(fields, 'p90_radiance', 'P90 辐亮', nightlight.p90_radiance)
        this.appendBasisField(fields, 'lit_pixel_ratio', '点亮占比', nightlight.lit_pixel_ratio)
        this.appendBasisField(fields, 'peak_to_edge_ratio', '峰值边缘比', nightlight.peak_to_edge_ratio)
        this.appendBasisField(fields, 'sector_direction_analysis', '夜光扇区方位', nightlight.sector_direction_analysis)
        this.appendBasisField(fields, 'road_orientation_analysis', '路网方位', this.summarizeRoadOrientationAnalysis(road.road_orientation_analysis))
        this.appendBasisField(fields, 'road_pattern_summary', '路网摘要', road.summary_text)
      }
      this.appendBasisField(fields, 'area_facts', '区域空间事实', evidence.area_facts)
      return fields.filter((field) => this.hasBasisFieldValue(field.value))
    },
    buildAgentSummaryBasisPayload(item = null) {
      const section = item && typeof item === 'object' ? item : {}
      const key = asText(section.sectionKey || section.section_key)
      const panelPayloads = this.getAgentActiveSummaryPanelPayloads()
      const pack = this.getAgentSummaryPack(panelPayloads)
      const evidence = this.buildAgentSummaryEvidencePack(panelPayloads)
      const fields = this.buildAgentSummaryEvidenceFields(section, evidence)
      const snapshots = cloneObject(panelPayloads.prompt_snapshots || pack.prompt_snapshots || {})
      const validationResults = cloneObject(panelPayloads.validation_results || pack.validation_results || {})
      const promptSnapshot = cloneObject(snapshots[key] || {})
      const promptDisplay = this.resolveBasisPromptDisplay(key, promptSnapshot)
      return {
        title: `${asText(section.title) || '区域总结'}依据`,
        currentConclusion: asText(section.reasoning),
        fields,
        rules: [],
        template: '',
        aiPrompt: promptDisplay.aiPrompt,
        aiPromptPayloadNote: promptDisplay.aiPromptPayloadNote,
        outputSchema: promptDisplay.outputSchema,
        promptKey: key,
        promptSnapshot: promptDisplay.promptSnapshot,
        promptSourceLabel: promptDisplay.promptSourceLabel,
        validationResults: validationResults[key] ? { [key]: cloneObject(validationResults[key]) } : {},
        rawInput: {
          section,
          generated_section: key === 'headline'
            ? cloneObject((pack.headline_judgment || {}))
            : cloneObject((pack[key] || pack[`${key}`] || {})),
          evidence,
        },
        sourceType: 'ai_checked',
      }
    },
    buildNightlightBasisPayload() {
      const summary = cloneObject((this.nightlightOverview && this.nightlightOverview.summary) || (this.nightlightLayer && this.nightlightLayer.summary) || {})
      const analysis = cloneObject((this.nightlightLayer && this.nightlightLayer.analysis) || {})
      const summaryRows = typeof this.getNightlightSummaryRows === 'function' ? this.getNightlightSummaryRows() : []
      const sector = cloneObject(analysis.sector_direction_analysis || summary.sector_direction_analysis || {})
      const conclusion = asText(
        `mean_radiance=${analysis.mean_radiance ?? summary.mean_radiance ?? '-'}; `
        + `lit_pixel_ratio=${analysis.lit_pixel_ratio ?? summary.lit_pixel_ratio ?? '-'}; `
        + `dominant_direction=${sector.dominant_direction || '-'}.`,
      )
      return {
        title: '夜光分析指标说明',
        currentConclusion: conclusion,
        fields: [
          ...summaryRows.map((row) => ({ key: row.key, label: row.label, value: row.value })),
          { key: 'p90_radiance', label: '夜光 P90', value: analysis.p90_radiance ?? summary.p90_radiance },
          { key: 'sector_direction_analysis', label: '扇区方位数值', value: sector },
          { key: 'peak_to_edge_ratio', label: '峰值边缘比', value: analysis.peak_to_edge_ratio },
        ],
        rules: [],
        template: '',
        aiPrompt: '',
        rawInput: {
          summary,
          analysis,
          active_view: this.nightlightAnalysisView,
        },
        sourceType: 'rule',
      }
    },
    buildRoadSyntaxBasisPayload() {
      const summary = cloneObject(this.roadSyntaxSummary || {})
      const orientation = cloneObject(summary.road_orientation_analysis || {})
      return {
        title: '路网分析数据',
        currentConclusion: '',
        fields: [
          { key: 'node_count', label: '节点数量', value: summary.node_count },
          { key: 'edge_count', label: '边数量', value: summary.edge_count },
          { key: 'total_length_m', label: '道路总长度', value: summary.total_length_m },
          { key: 'road_orientation_analysis', label: '路网方位分析', value: orientation },
          { key: 'metric', label: '当前指标', value: this.roadSyntaxMetric || this.roadSyntaxLastMetricTab },
          { key: 'radius', label: '分析半径', value: this.roadSyntaxRadius },
        ],
        rules: [],
        template: '',
        aiPrompt: '',
        rawInput: {
          summary,
          diagnostics: {
            status: (this.roadSyntaxDiagnostics || {}).status,
            warning: (this.roadSyntaxDiagnostics || {}).warning,
            error: (this.roadSyntaxDiagnostics || {}).error,
          },
          metric: this.roadSyntaxMetric,
          radius: this.roadSyntaxRadius,
        },
        sourceType: 'rule',
      }
    },
    getAgentIterationNightlightSystemPrompt() {
      return this.getPromptMissingMessage('nightlight_iteration')
    },
    getAgentIterationNightlightPromptPayloadNote() {
      return ''
    },
    buildAgentIterationBasisPayload(kind = 'poi', section = '') {
      const safeKind = asText(kind) || 'poi'
      const safeSection = asText(section)
      const payload = this.getAgentIterationPayload(safeKind)
      const isNightlight = safeKind === 'nightlight'
      const isPoi = safeKind === 'poi'
      const isPoiInsight = isPoi && safeSection === 'insight'
      const isPoiAnalysis = isPoi && safeSection === 'analysis'
      const rawInput = isPoi
        ? this.buildAgentPoiIterationAiEvidencePreview(payload)
        : this.buildAgentNightlightIterationEvidence(payload)
      const promptKey = isPoi ? 'poi_iteration' : 'nightlight_iteration'
      const promptSnapshots = cloneObject(payload.prompt_snapshots || payload.promptSnapshots || {})
      const promptSnapshot = cloneObject(payload.prompt_snapshot || payload.promptSnapshot || promptSnapshots[promptKey] || {})
      const allValidationResults = cloneObject(payload.validation_results || payload.validationResults || {})
      const validationResult = cloneObject(allValidationResults[promptKey] || {})
      const promptDisplay = this.resolveBasisPromptDisplay(promptKey, promptSnapshot)
      const evidenceYears = cloneArray(rawInput.years)
      const evidenceYearSummaries = cloneArray(rawInput.year_summaries)
      const latestEvidenceYear = evidenceYearSummaries[evidenceYearSummaries.length - 1] || {}
      const evidenceTrendMetrics = cloneArray(rawInput.trend_metrics)
      const evidenceCategoryChanges = cloneArray(rawInput.category_changes)
      const evidenceSubcategoryChanges = cloneArray(rawInput.subcategory_changes)
      const evidenceSpatialTrends = cloneArray(rawInput.subcategory_spatial_trends)
      const evidenceAreaDistribution = cloneArray(rawInput.area_distribution)
      const h3Evidence = cloneObject(rawInput.h3_evidence)
      const yearlyGridEvidence = cloneObject(rawInput.yearly_grid_evidence)
      const nightlightSeries = cloneArray(rawInput.series)
      const nightlightHotspot = cloneObject(rawInput.hotspot_shift)
      const nightlightSnapshotRefs = cloneArray(rawInput.snapshot_refs)
      const findMetricValue = (key, fallbackLabel = '') => {
        const row = evidenceTrendMetrics.find((item) => asText(item && item.key) === key)
          || evidenceTrendMetrics.find((item) => fallbackLabel && asText(item && item.label).includes(fallbackLabel))
        return row ? row.value : ''
      }
      const formatChangeName = (row = null) => {
        if (!row || typeof row !== 'object') return ''
        const name = asText(row.name)
        const parent = asText(row.parent)
        const delta = Number(row.delta || 0)
        return `${name}${parent ? `（${parent}）` : ''} ${delta >= 0 ? '+' : ''}${delta}`
      }
      const strongestGrowth = (rows) => cloneArray(rows)
        .filter((row) => Number(row && row.delta) > 0)
        .sort((a, b) => Number(b.delta || 0) - Number(a.delta || 0))[0]
      const strongestDecline = (rows) => cloneArray(rows)
        .filter((row) => Number(row && row.delta) < 0)
        .sort((a, b) => Number(a.delta || 0) - Number(b.delta || 0))[0]
      const poiEvidenceFields = [
        { key: 'evidence_version', label: '证据包版本', value: rawInput.evidence_version },
        { key: 'period', label: '分析周期', value: evidenceYears.length ? `${evidenceYears[0]}-${evidenceYears[evidenceYears.length - 1]}` : payload.period },
        { key: 'scope', label: '分析范围', value: `${asText((rawInput.scope || {}).area_name) || '未命名区域'} · ${asText((rawInput.scope || {}).scope_type) || '-'}` },
        { key: 'latest_total', label: '末年 POI 数量', value: latestEvidenceYear.poi_count },
        { key: 'total_delta', label: 'POI 首尾变化', value: findMetricValue('total_delta', 'POI 首尾变化') },
        { key: 'category_growth', label: '增长最明显业态', value: findMetricValue('top_increase') || formatChangeName(strongestGrowth(evidenceCategoryChanges)) },
        { key: 'category_decline', label: '减少最明显业态', value: findMetricValue('top_decrease') || formatChangeName(strongestDecline(evidenceCategoryChanges)) },
        { key: 'subcategory_growth', label: '增长最明显小类', value: findMetricValue('top_subcategory_increase') || formatChangeName(strongestGrowth(evidenceSubcategoryChanges)) },
        { key: 'subcategory_decline', label: '减少最明显小类', value: findMetricValue('top_subcategory_decrease') || formatChangeName(strongestDecline(evidenceSubcategoryChanges)) },
        { key: 'spatial_signal_count', label: '小类空间信号', value: evidenceSpatialTrends.length ? `${evidenceSpatialTrends.length} 条` : '暂无，可能仍在生成或后端未返回' },
        { key: 'area_distribution', label: '年度区域分布', value: evidenceAreaDistribution.map((row) => `${row.year || '-'}：${row.point_count ?? '-'}点，热点${row.hotspot_cell_count ?? 0}格`) },
        { key: 'h3_evidence', label: '末年 H3 网格证据', value: h3Evidence },
        { key: 'yearly_grid_evidence', label: '年度网格证据', value: yearlyGridEvidence },
      ].filter((item) => item.value !== undefined && item.value !== null && item.value !== '')
      const poiAnalysisFields = poiEvidenceFields
        .filter((field) => [
          'evidence_version',
          'period',
          'scope',
          'latest_total',
          'total_delta',
          'category_growth',
          'category_decline',
          'subcategory_growth',
          'subcategory_decline',
          'h3_evidence',
          'yearly_grid_evidence',
        ].includes(field.key))
        .concat([
          { key: 'prompt_structure', label: '提示词结构', value: '同一基础提示词；本块读取业态基础分析长文报告，并结合 H3 与年度网格证据。' },
          { key: 'output_fields', label: '本块使用输出字段', value: 'report_title, report_sections, report_content' },
        ])
      const poiInsightFields = [
        { key: 'evidence_version', label: '证据包版本', value: rawInput.evidence_version },
        { key: 'period', label: '分析周期', value: evidenceYears.length ? `${evidenceYears[0]}-${evidenceYears[evidenceYears.length - 1]}` : payload.period },
        { key: 'scope', label: '分析范围', value: `${asText((rawInput.scope || {}).area_name) || '未命名区域'} · ${asText((rawInput.scope || {}).scope_type) || '-'}` },
        { key: 'material_change_highlights', label: '增长/衰退排序依据', value: rawInput.material_change_highlights },
        { key: 'growth_area_signal', label: '增长片区信号', value: rawInput.growth_area_signal },
        { key: 'spatial_signal_count', label: '小类空间信号', value: evidenceSpatialTrends.length ? `${evidenceSpatialTrends.length} 条` : '暂无，可能仍在生成或后端未返回' },
        { key: 'area_distribution', label: '年度区域分布', value: evidenceAreaDistribution.map((row) => `${row.year || '-'}：${row.point_count ?? '-'}点，热点${row.hotspot_cell_count ?? 0}格`) },
        { key: 'h3_evidence', label: '末年 H3 网格证据', value: h3Evidence },
        { key: 'yearly_grid_evidence', label: '年度网格证据', value: yearlyGridEvidence },
        { key: 'prompt_structure', label: '提示词结构', value: '同一基础提示词；本块读取业态基础分析长文报告，并结合 H3 与年度网格证据。' },
        { key: 'output_fields', label: '本块使用输出字段', value: 'report_title, report_sections, report_content' },
      ].filter((item) => item.value !== undefined && item.value !== null && item.value !== '')
      const conclusionRows = isNightlight
        ? this.getAgentIterationNightlightAnalysisRows().map((row) => `${row.label}：${row.value}`)
        : isPoiInsight
          ? this.getAgentIterationPoiReportSections().flatMap((section) => [section.heading, ...section.paragraphs])
          : [
              ...this.getAgentIterationPoiReportSections().flatMap((section) => [section.heading, ...section.paragraphs]),
            ]
      return {
        title: isNightlight ? '夜光多年变化依据' : isPoiInsight ? 'POI 多年洞察依据' : isPoiAnalysis ? 'POI 多年分析依据' : 'POI 多年变化依据',
        currentConclusion: conclusionRows.join('\n') || '当前暂无可展示结论。',
        fields: isNightlight
          ? [
            { key: 'evidence_version', label: '证据包版本', value: rawInput.evidence_version },
            { key: 'period', label: '分析周期', value: payload.period },
            { key: 'years', label: '覆盖年份', value: cloneArray(rawInput.years).join('-') },
            { key: 'series_count', label: '年度统计条数', value: nightlightSeries.length },
            { key: 'trend_rows', label: '趋势指标', value: this.getAgentIterationNightlightTrendRows() },
            { key: 'hotspot_rows', label: '热点变化', value: this.getAgentIterationNightlightHotspotRows() },
            { key: 'hotspot_shift', label: '热点迁移摘要', value: nightlightHotspot },
            { key: 'snapshot_refs', label: '快照引用', value: nightlightSnapshotRefs.map((item) => `${item.year || '-'}：${item.has_image ? '有快照' : '无快照'}，${item.has_vector ? '有矢量' : '无矢量'}`) },
          ].filter((item) => item.value !== undefined && item.value !== null && item.value !== '')
          : isPoiInsight ? poiInsightFields : isPoiAnalysis ? poiAnalysisFields : poiEvidenceFields,
        rules: [
          '多年迭代先抽取年度快照和结构化指标，再生成趋势判断。',
          'AI 输出会被后端要求按固定 JSON 字段返回，前端只展示通过校验的字段。',
          isPoi
            ? isPoiInsight
              ? '这是同一轮 POI 多年解读中的报告字段，不是重复调用；本块展示业态基础分析总结报告。'
              : isPoiAnalysis
                ? '这是同一轮 POI 多年解读中的业态基础分析报告字段，不是重复调用；本块展示完整章节正文。'
                : 'POI 分析关注总量、业态结构、区域分布与增长/衰退方向。'
            : '夜光分析关注总辐亮、均值、P90、点亮占比和热点迁移。',
        ],
        template: isPoi
          ? isPoiInsight
            ? '从同一轮 POI 多年解读结果中读取{报告标题}、{章节正文}与{完整报告文本}。'
            : isPoiAnalysis
              ? '从同一轮 POI 多年解读结果中读取 report_sections，组织业态基础分析长文报告。'
              : '基于{年份序列}的 POI 总量、业态结构和区域分布变化，概括{趋势判断}、{结构变化}与{机会风险}。'
          : '基于近三年夜光快照，概括{趋势判断}、{总体变化}、{热点迁移}与{机会风险}。',
        aiPrompt: promptDisplay.aiPrompt,
        aiPromptPayloadNote: promptDisplay.aiPromptPayloadNote,
        outputSchema: promptDisplay.outputSchema,
        promptKey,
        promptSnapshot: promptDisplay.promptSnapshot,
        promptSourceLabel: promptDisplay.promptSourceLabel,
        validationResults: Object.keys(validationResult).length ? { [promptKey]: validationResult } : {},
        rawInput,
        sourceType: 'ai_checked',
      }
    },
    getBasisValidationResultItems() {
      const payload = this.getBasisDrawerPayload()
      const validationResults = payload.validationResults && typeof payload.validationResults === 'object'
        ? payload.validationResults
        : {}
      return Object.entries(validationResults).map(([key, item]) => ({
        key,
        title: asText((item && item.prompt_key) || key),
        status: asText(item && item.status) || 'unknown',
        note: asText(item && item.note),
        evidenceVersion: asText(item && item.evidence_version),
        outputSchema: cloneObject(item && item.output_schema),
        validatedOutput: cloneObject(item && item.validated_output),
        checks: cloneArray(item && item.checks),
      }))
    },
    getAgentInputPackageStatus(item = {}) {
      const value = item && typeof item === 'object' ? item.rawInput : null
      if (!value || (typeof value === 'object' && !Array.isArray(value) && !Object.keys(value).length)) return 'missing'
      if (item.requiredVersion && asText(value.evidence_version) !== asText(item.requiredVersion)) return 'partial'
      if (item.key === 'shared_grid' && Number(value.counts && value.counts.complete_overlap_cells || 0) <= 0) return 'partial'
      return 'ready'
    },
    getAgentInputPackageStatusLabel(item = {}) {
      const status = this.getAgentInputPackageStatus(item)
      if (status === 'ready') return '已就绪'
      if (status === 'partial') return '部分可用'
      return '未就绪'
    },
    createAgentInputPackageItem({ key, title, description, sourcePath, rawInput, requiredVersion = '', fields = [] }) {
      const item = {
        key: asText(key),
        title: asText(title),
        description: asText(description),
        sourcePath: asText(sourcePath),
        rawInput: cloneObject(rawInput || {}),
        requiredVersion: asText(requiredVersion),
        fields: cloneArray(fields),
      }
      return {
        ...item,
        status: this.getAgentInputPackageStatus(item),
        summary: this.summarizeAgentInputPackage(item.rawInput),
      }
    },
    buildAgentInputPackageGroups() {
      const snapshot = typeof this.buildAgentAnalysisSnapshot === 'function'
        ? this.buildAgentAnalysisSnapshot()
        : {}
      const paramBundles = snapshot.param_bundles && typeof snapshot.param_bundles === 'object' ? snapshot.param_bundles : {}
      const paramOrder = ['poi_fetch', 'poi_raster_grid', 'poi_h3_grid', 'population', 'nightlight', 'road_syntax']
      const paramItems = paramOrder
        .filter((key) => paramBundles[key])
        .map((key) => this.createAgentInputPackageItem({
          key: `param_${key}`,
          title: key,
          description: asText(paramBundles[key].display_label) || '分析任务参数口径',
          sourcePath: `param_bundles.${key}`,
          rawInput: paramBundles[key],
          fields: [
            { key: 'task_key', label: '任务', value: paramBundles[key].task_key },
            { key: 'domain', label: '领域', value: paramBundles[key].domain },
            { key: 'version', label: '版本', value: paramBundles[key].version },
            { key: 'cache_key', label: '缓存键', value: paramBundles[key].cache_key },
          ],
        }))
      const sharedGrid = cloneObject(snapshot.shared_grid || {})
      const poiH3 = cloneObject(snapshot.h3 && snapshot.h3.poi_h3_evidence || {})
      return [
        {
          key: 'param_bundles',
          label: '分析参数包',
          description: '当前任务的计算口径、缓存键和 evidence 参数。',
          items: paramItems,
        },
        {
          key: 'shared_grid',
          label: '同源栅格交叉证据',
          description: '人口、POI 共享栅格、夜光按同一 cell_id 对齐后的交叉证据。',
          items: [
            this.createAgentInputPackageItem({
              key: 'shared_grid',
              title: 'shared_grid_evidence_v1',
              description: '只用于人口 × POI × 夜光空间耦合判断。',
              sourcePath: 'shared_grid',
              rawInput: sharedGrid,
              requiredVersion: 'shared_grid_evidence_v1',
              fields: [
                { key: 'evidence_version', label: '证据版本', value: sharedGrid.evidence_version },
                { key: 'join_key', label: '连接键', value: sharedGrid.join_key },
                { key: 'uses', label: '使用数据', value: sharedGrid.uses },
                { key: 'counts', label: '计数', value: sharedGrid.counts },
              ],
            }),
          ],
        },
        {
          key: 'poi_spatial',
          label: 'POI 专项空间证据',
          description: 'POI H3 专项空间结构证据；POI 共享栅格只通过 shared_grid 参与耦合判断。',
          items: [
            this.createAgentInputPackageItem({
              key: 'poi_h3',
              title: 'poi_h3_evidence_v1',
              description: '只用于 POI 密度、集聚、熵、Gi/LISA 和热点结构判断。',
              sourcePath: 'h3.poi_h3_evidence',
              rawInput: poiH3,
              requiredVersion: 'poi_h3_evidence_v1',
              fields: [
                { key: 'evidence_version', label: '证据版本', value: poiH3.evidence_version },
                { key: 'grid_type', label: '网格类型', value: poiH3.grid_type },
                { key: 'counts', label: '计数', value: poiH3.counts },
                { key: 'metrics', label: '指标', value: poiH3.metrics },
              ],
            }),
          ],
        },
        {
          key: 'summary_evidence',
          label: '总结输入 evidence',
          description: 'summary/tourism payload 会读取的当前压缩证据对象。',
          items: [
            this.createAgentInputPackageItem({ key: 'summary_population', title: 'population', description: '人口 summary 与 grid_evidence。', sourcePath: 'population', rawInput: snapshot.population || {} }),
            this.createAgentInputPackageItem({ key: 'summary_nightlight', title: 'nightlight', description: '夜光 summary。', sourcePath: 'nightlight', rawInput: snapshot.nightlight || {} }),
            this.createAgentInputPackageItem({ key: 'summary_poi', title: 'poi_summary', description: 'POI 总量和来源；栅格耦合读取 shared_grid。', sourcePath: 'poi_summary', rawInput: snapshot.poi_summary || {} }),
            this.createAgentInputPackageItem({ key: 'summary_frontend', title: 'frontend_analysis', description: '前端导出的结构化分析块。', sourcePath: 'frontend_analysis', rawInput: snapshot.frontend_analysis || {} }),
          ],
        },
      ]
    },
    buildAgentInputPackageBasisPayload(packageItem = {}) {
      const item = packageItem && typeof packageItem === 'object' ? packageItem : {}
      return {
        title: `${asText(item.title) || '输入包'}字段`,
        currentConclusion: asText(item.description) || '当前输入包字段预览。',
        fields: [
          { key: 'status', label: '状态', value: this.getAgentInputPackageStatusLabel(item) },
          { key: 'source_path', label: '来源对象', value: item.sourcePath },
          { key: 'summary', label: '摘要', value: item.summary || this.summarizeAgentInputPackage(item.rawInput) },
          ...cloneArray(item.fields),
        ],
        rules: [
          '输入包为只读预览，用于查看当前会传给总结、文旅分析或 Agent 的参数口径与证据。',
          '同源栅格交叉证据只使用 shared_grid_evidence_v1；H3 只作为 POI 专项空间结构证据。',
        ],
        template: '从当前 analysis snapshot 中读取{来源对象}，用于检查 AI 输入口径和证据边界。',
        aiPrompt: '未调用 AI。该抽屉展示当前前端运行态 snapshot 中的输入包字段。',
        rawInput: cloneObject(item.rawInput || {}),
        sourceType: 'rule',
      }
    },
  }
}
