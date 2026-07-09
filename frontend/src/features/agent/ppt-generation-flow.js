import { asText, cloneArray, cloneObject } from './normalizers.js'
import { normalizePptGenerationErrorMessage } from './ppt-generation-errors.js'
import {
  appendPptGenerationDebugEvent,
  buildDeckBriefPayload,
  buildNarrativePlanPayload,
  buildPptSpecPayload,
  collectPptVisualArtifactFilenames,
  completePptGenerationJob,
  createPptPlanningState,
  failPptGenerationJob,
  getPptSourceDeliveryManifest,
  getPptSourceSummary,
  hasPptBlockingInputs,
  resetPptPlanningToMaterials,
  resetPptPlanningToNarrativeReady,
  resetPptPlanningToOutlineReady,
  startPptDeckBriefJob,
  startPptGenerationJob,
  updatePptDeckBriefJobState,
} from '../ppt-planning/ui-state.js'

function createPptGenerationRequestId(type = '') {
  const random = typeof globalThis.crypto !== 'undefined' && typeof globalThis.crypto.randomUUID === 'function'
    ? globalThis.crypto.randomUUID()
    : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
  return `ppt-${asText(type) || 'generation'}-${random}`
}

function appendPptDebugEventToState(state = {}, eventName = '', details = {}) {
  return appendPptGenerationDebugEvent(createPptPlanningState(state), eventName, details)
}

function delay(ms = 0) {
  return new Promise((resolve) => globalThis.setTimeout(resolve, ms))
}

async function waitForPptDeckBriefJob(jobId = '', { attempts = 80, intervalMs = 1500, getJob } = {}) {
  const normalizedJobId = asText(jobId)
  if (!normalizedJobId || typeof getJob !== 'function') return null
  for (let index = 0; index < attempts; index += 1) {
    const job = await getJob(normalizedJobId)
    const status = asText(job && job.status)
    if (status === 'completed' || status === 'failed') return job
    await delay(intervalMs)
  }
  return null
}

function createPptRuntimeEventWriter(ctx = {}, tabId = '', requestId = '', type = '') {
  const writeRuntimeState = (nextState = {}) => ctx.updateAgentPptPlanningTabRuntimeState(tabId, nextState)
  return (name = '', details = {}) => {
    try {
      return writeRuntimeState(appendPptDebugEventToState(
        ctx.getAgentPptPlanningTabState(tabId),
        name,
        { requestId, tabId, type, ...cloneObject(details) },
      ))
    } catch (error) {
      if (typeof console !== 'undefined' && console.error) console.error(`PPT ${type} runtime event failed`, error)
      return false
    }
  }
}

export function createAgentPptGenerationFlowMethods() {
  return {
    async generateAgentPptPlanningOutline() {
      const activeTab = this.getAgentActivePptPlanningTab()
      const tabId = asText(activeTab && activeTab.id)
      if (!tabId) return
      const state = this.getAgentPptPlanningStateWithSystemSources()
      if (!getPptSourceSummary(state).selected) return
      if (hasPptBlockingInputs(state)) return
      const manifest = getPptSourceDeliveryManifest(state)
      if (!manifest.deliverableSources.length) {
        const requestId = createPptGenerationRequestId('outline-preflight')
        const failedState = failPptGenerationJob(
          startPptGenerationJob(state, { requestId, type: 'outline', tabId }),
          requestId,
          '当前已选来源没有可发送给 AI 的指标或证据，请刷新来源或重新选择来源。',
          { source: 'outline' },
        )
        this.updateAgentPptPlanningTabState(tabId, appendPptDebugEventToState(failedState, 'source_payload_preflight_failed', {
          selectedSourceIds: manifest.sourceIds,
          deliverableSourceIds: manifest.deliverableSourceIds,
          emptyPayloadSourceIds: manifest.emptyPayloadSourceIds,
        }))
        return
      }
      const requestId = createPptGenerationRequestId('outline')
      const writeRuntimeState = (nextState = {}) => this.updateAgentPptPlanningTabRuntimeState(tabId, nextState)
      const writeRuntimeEvent = createPptRuntimeEventWriter(this, tabId, requestId, 'outline')
      writeRuntimeState(startPptGenerationJob(state, { requestId, type: 'outline', tabId }))
      writeRuntimeEvent('outline_start_dispatched')
      const heartbeatId = globalThis.setInterval(() => {
        writeRuntimeEvent('generation_heartbeat')
      }, 10000)
      writeRuntimeEvent('heartbeat_scheduled', { intervalMs: 10000 })
      let response = null
      try {
        const payload = buildPptSpecPayload(state, this.buildAgentPptPlanningApiContext())
        writeRuntimeEvent('source_payload_preflight', {
          selectedSourceIds: manifest.sourceIds,
          deliverableSourceIds: manifest.deliverableSourceIds,
          emptyPayloadSourceIds: manifest.emptyPayloadSourceIds,
          payloadSourceCount: cloneArray(payload.sources).length,
        })
        response = await this.requestAgentPptPlanningOutlineWithDebug(
          payload,
          { onDebugEvent: (name = '', details = {}) => writeRuntimeEvent(name, details) },
        )
        writeRuntimeEvent('fetch_resolved')
        writeRuntimeEvent('json_or_api_returned', {
          outlineCount: cloneArray(response && response.outline).length,
          keys: Object.keys(response || {}).slice(0, 8),
        })
        const currentState = this.getAgentPptPlanningTabStateWithSystemSources(tabId)
        this.updateAgentPptPlanningTabState(tabId, completePptGenerationJob(currentState, requestId, response))
      } catch (error) {
        writeRuntimeEvent('fetch_failed', {
          kind: asText(error && error.kind),
          code: asText(error && error.code),
          message: asText(error && error.message ? error.message : error),
        })
        this.updateAgentPptPlanningTabState(tabId, failPptGenerationJob(
          this.getAgentPptPlanningTabStateWithSystemSources(tabId),
          requestId,
          normalizePptGenerationErrorMessage(error, 'outline'),
          { source: 'outline', generationResponse: response || error?.response || error?.data || {} },
        ))
      } finally {
        globalThis.clearInterval(heartbeatId)
      }
    },
    async generateAgentPptPlanningDirective() {
      const activeTab = this.getAgentActivePptPlanningTab()
      const tabId = asText(activeTab && activeTab.id)
      if (!tabId) return
      const state = this.getAgentPptPlanningStateWithSystemSources()
      if (!cloneArray(state.outline).length) return
      const staleFilenames = collectPptVisualArtifactFilenames(state.deckBrief)
      const requestId = createPptGenerationRequestId('directive')
      const writeRuntimeEvent = createPptRuntimeEventWriter(this, tabId, requestId, 'directive')
      try {
        const payload = buildDeckBriefPayload(state, this.buildAgentPptPlanningApiContext())
        const createResponse = await this.requestAgentPptPlanningDeckBriefJob(payload)
        const briefJobId = asText(createResponse && createResponse.job_id)
        if (!briefJobId) {
          throw Object.assign(new Error('ppt_deck_brief_job_missing_id'), {
            kind: 'invalid_response',
            code: 'ppt_deck_brief_job_missing_id',
          })
        }
        const createdState = startPptDeckBriefJob(state, { jobId: briefJobId, updatedAt: createResponse.updated_at })
        this.updateAgentPptPlanningTabState(tabId, appendPptDebugEventToState(
          createdState,
          'directive_job_created',
          { requestId, briefJobId, status: createResponse.status || 'queued' },
        ))
        writeRuntimeEvent('directive_job_created', { briefJobId, status: createResponse.status || 'queued' })
        const heartbeatId = globalThis.setInterval(() => {
          writeRuntimeEvent('generation_heartbeat')
        }, 10000)
        writeRuntimeEvent('heartbeat_scheduled', { intervalMs: 10000 })
        let polled = null
        try {
          polled = await waitForPptDeckBriefJob(briefJobId, {
            getJob: (jobId) => this.requestAgentPptPlanningDeckBriefJobStatus(jobId),
          })
        } finally {
          globalThis.clearInterval(heartbeatId)
        }
        if (!polled) {
          throw Object.assign(new Error('ppt_deck_brief_job_poll_timeout'), {
            kind: 'timeout',
            code: 'ppt_deck_brief_job_poll_timeout',
            detail: { briefJobId },
          })
        }
        if (asText(polled.status) === 'failed') {
          const jobError = cloneObject(polled.error)
          throw Object.assign(new Error(asText(jobError.message || jobError.code) || 'ppt_deck_brief_job_failed'), {
            kind: 'job_failed',
            code: asText(jobError.code) || 'ppt_deck_brief_job_failed',
            detail: cloneObject(jobError.detail),
            jobError,
          })
        }
        if (asText(polled.status) !== 'completed') {
          throw Object.assign(new Error('ppt_deck_brief_job_unexpected_status'), {
            kind: 'invalid_response',
            code: 'ppt_deck_brief_job_unexpected_status',
            detail: { briefJobId, status: asText(polled.status) },
          })
        }
        const currentState = this.getAgentPptPlanningTabStateWithSystemSources(tabId)
        const result = polled.result || {}
        writeRuntimeEvent('directive_response_unwrapped', {
          currentJobId: asText(currentState.briefJobId || currentState.brief_job_id),
          briefJobId,
          slideCount: cloneArray(result && result.slides).length,
          keys: Object.keys(result || {}).slice(0, 8),
        })
        writeRuntimeEvent('directive_apply_start', {
          briefJobId,
          slideCount: cloneArray(result && result.slides).length,
          keys: Object.keys(result || {}).slice(0, 8),
        })
        const expectedSlideCount = cloneArray(result && result.slides).length
        const appliedState = updatePptDeckBriefJobState(
          appendPptDebugEventToState(
            appendPptDebugEventToState(currentState, 'directive_response_unwrapped', {
              requestId,
              briefJobId,
              slideCount: expectedSlideCount,
              keys: Object.keys(result || {}).slice(0, 8),
            }),
            'directive_apply_start',
            {
              requestId,
              briefJobId,
              slideCount: expectedSlideCount,
              keys: Object.keys(result || {}).slice(0, 8),
            },
          ),
          {
            job_id: briefJobId,
            status: 'completed',
            progress: polled.progress || { stage: 'completed' },
            result,
            updated_at: polled.updated_at || new Date().toISOString(),
          },
        )
        const completedState = cloneArray((appliedState.deckBrief || {}).slides).length
          ? appendPptDebugEventToState(
            appliedState,
            'directive_apply_done',
            { requestId, briefJobId, slideCount: cloneArray((appliedState.deckBrief || {}).slides).length },
          )
          : appliedState
        this.updateAgentPptPlanningTabState(tabId, completedState)
        const syncedSlides = cloneArray((this.getAgentPptPlanningTabState(tabId).deckBrief || {}).slides)
        if (expectedSlideCount > 0 && !syncedSlides.length) {
          throw Object.assign(new Error('ppt_deck_brief_writeback_missing'), {
            kind: 'invalid_writeback',
            code: 'ppt_deck_brief_writeback_missing',
            detail: { briefJobId, expectedSlideCount },
          })
        }
        if (cloneArray((completedState.deckBrief || {}).slides).length) {
          this.cleanupAgentPptPlanningVisualArtifacts(staleFilenames)
        }
      } catch (error) {
        writeRuntimeEvent('fetch_failed', {
          kind: asText(error && error.kind),
          code: asText(error && error.code),
          message: asText(error && error.message ? error.message : error),
        })
        const currentState = this.getAgentPptPlanningTabStateWithSystemSources(tabId)
        const jobId = asText(currentState.briefJobId || currentState.brief_job_id)
        if (jobId) {
          this.updateAgentPptPlanningTabState(tabId, updatePptDeckBriefJobState(currentState, {
            job_id: jobId,
            status: 'failed',
            error: {
              code: asText(error && error.code) || 'ppt_deck_brief_job_failed',
              message: normalizePptGenerationErrorMessage(error, 'directive'),
              detail: error && error.detail ? error.detail : {},
            },
            progress: { stage: 'failed', message: 'brief 生成失败' },
            updated_at: new Date().toISOString(),
          }))
        } else {
          this.updateAgentPptPlanningTabState(tabId, failPptGenerationJob(
            this.getAgentPptPlanningTabStateWithSystemSources(tabId),
            requestId,
            normalizePptGenerationErrorMessage(error, 'directive'),
            { source: 'directive' },
          ))
        }
      }
    },
    async generateAgentPptPlanningNarrativePlan() {
      const activeTab = this.getAgentActivePptPlanningTab()
      const tabId = asText(activeTab && activeTab.id)
      if (!tabId) return
      const state = this.getAgentPptPlanningStateWithSystemSources()
      if (!cloneArray(state.outline).length) return
      const requestId = createPptGenerationRequestId('narrative')
      const writeRuntimeState = (nextState = {}) => this.updateAgentPptPlanningTabRuntimeState(tabId, nextState)
      const writeRuntimeEvent = createPptRuntimeEventWriter(this, tabId, requestId, 'narrative')
      writeRuntimeState(startPptGenerationJob(state, { requestId, type: 'narrative', tabId }))
      writeRuntimeEvent('narrative_start_dispatched')
      const heartbeatId = globalThis.setInterval(() => {
        writeRuntimeEvent('generation_heartbeat')
      }, 10000)
      let response = null
      try {
        response = await this.requestAgentPptPlanningNarrativePlanWithDebug(
          buildNarrativePlanPayload(state, this.buildAgentPptPlanningApiContext()),
          { onDebugEvent: (name = '', details = {}) => writeRuntimeEvent(name, details) },
        )
        writeRuntimeEvent('json_or_api_returned', {
          roleCount: cloneArray(response && (response.slide_roles || response.slideRoles)).length,
          keys: Object.keys(response || {}).slice(0, 8),
        })
        const completedState = completePptGenerationJob(
          this.getAgentPptPlanningTabStateWithSystemSources(tabId),
          requestId,
          response,
        )
        this.updateAgentPptPlanningTabState(tabId, completedState)
      } catch (error) {
        writeRuntimeEvent('fetch_failed', {
          kind: asText(error && error.kind),
          code: asText(error && error.code),
          message: asText(error && error.message ? error.message : error),
        })
        this.updateAgentPptPlanningTabState(tabId, failPptGenerationJob(
          this.getAgentPptPlanningTabStateWithSystemSources(tabId),
          requestId,
          normalizePptGenerationErrorMessage(error, 'narrative'),
          { source: 'narrative', generationResponse: response || error?.response || error?.data || {} },
        ))
      } finally {
        globalThis.clearInterval(heartbeatId)
      }
    },
    confirmAgentPptPlanningStepReset(message = '') {
      if (typeof this.confirmPptPlanningStepReset === 'function') {
        return this.confirmPptPlanningStepReset(message)
      }
      if (typeof window === 'undefined' || typeof window.confirm !== 'function') return true
      return window.confirm(message)
    },
    async regenerateAgentPptPlanningOutlineWithConfirm() {
      const state = this.getAgentPptPlanningStateWithSystemSources()
      const hasOutline = cloneArray(state.outline).length > 0
      const hasDirective = asText(state.currentStep) === 'directive_draft' && cloneArray((state.deckBrief || {}).slides).length > 0
      if (!hasOutline && !hasDirective) return
      if (!getPptSourceSummary(state).selected || hasPptBlockingInputs(state)) return
      const confirmed = await this.confirmAgentPptPlanningStepReset('重新生成目录会清空旧目录和旧指令文件，确认继续？')
      if (!confirmed) return
      const staleFilenames = collectPptVisualArtifactFilenames(state.deckBrief)
      this.updateAgentActivePptPlanningState(resetPptPlanningToMaterials(this.getAgentPptPlanningStateWithSystemSources()))
      this.cleanupAgentPptPlanningVisualArtifacts(staleFilenames)
      await this.generateAgentPptPlanningOutline()
    },
    async regenerateAgentPptPlanningDirectiveWithConfirm() {
      const state = this.getAgentPptPlanningStateWithSystemSources()
      const hasOutline = cloneArray(state.outline).length > 0
      const hasDirective = asText(state.currentStep) === 'directive_draft' && cloneArray((state.deckBrief || {}).slides).length > 0
      if (!hasOutline || !hasDirective) return
      const confirmed = await this.confirmAgentPptPlanningStepReset('重新生成 brief 会清空旧 brief，但保留当前目录和叙事方案，确认继续？')
      if (!confirmed) return
      const staleFilenames = collectPptVisualArtifactFilenames(state.deckBrief)
      this.updateAgentActivePptPlanningState(resetPptPlanningToOutlineReady(this.getAgentPptPlanningStateWithSystemSources()))
      this.cleanupAgentPptPlanningVisualArtifacts(staleFilenames)
      await this.generateAgentPptPlanningDirective()
    },
    async regenerateAgentPptPlanningNarrativePlanWithConfirm() {
      const state = this.getAgentPptPlanningStateWithSystemSources()
      const hasOutline = cloneArray(state.outline).length > 0
      if (!hasOutline) return
      const confirmed = await this.confirmAgentPptPlanningStepReset('重新生成叙事方案会清空旧叙事方案和逐页 brief，但保留当前目录，确认继续？')
      if (!confirmed) return
      const staleFilenames = collectPptVisualArtifactFilenames(state.deckBrief)
      this.updateAgentActivePptPlanningState(resetPptPlanningToOutlineReady(this.getAgentPptPlanningStateWithSystemSources()))
      this.cleanupAgentPptPlanningVisualArtifacts(staleFilenames)
      await this.generateAgentPptPlanningNarrativePlan()
    },
    async regenerateAgentPptPlanningSlidesWithConfirm() {
      const state = this.getAgentPptPlanningStateWithSystemSources()
      const hasNarrativePlan = cloneArray(state.narrativePlan && state.narrativePlan.slideRoles).length > 0
      if (!hasNarrativePlan) return
      const confirmed = await this.confirmAgentPptPlanningStepReset('重新生成 brief 会清空旧 brief，但保留当前目录和叙事方案，确认继续？')
      if (!confirmed) return
      const staleFilenames = collectPptVisualArtifactFilenames(state.deckBrief)
      this.updateAgentActivePptPlanningState(resetPptPlanningToNarrativeReady(this.getAgentPptPlanningStateWithSystemSources()))
      this.cleanupAgentPptPlanningVisualArtifacts(staleFilenames)
      await this.generateAgentPptPlanningSlides()
    },
  }
}
