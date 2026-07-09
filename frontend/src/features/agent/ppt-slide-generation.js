import { getAnalysisWorkspaceTabsFromState } from './analysis-workspace-tabs.js'
import { normalizePptGenerationErrorMessage } from './ppt-generation-errors.js'
import { asText, cloneArray } from './normalizers.js'
import {
  appendPptGenerationDebugEvent as appendPptDebugEventToState,
  applySlideResponseAndMarkReady,
  buildDeckBriefSlidePayload,
  markSlideApplying,
  markSlideFailed,
  markSlideRequestStarted,
  markSlideResponseReceived,
  markSlideTimedOut,
  startSlideGenerationQueue,
} from '../ppt-planning/ui-state.js'

const PPT_SLIDE_REQUEST_TIMEOUT_MS = 90000

export function createAgentPptSlideGenerationMethods() {
  return {
    async generateAgentPptPlanningSlides() {
      const activeTab = this.getAgentActivePptPlanningTab()
      const tabId = asText(activeTab && activeTab.id)
      if (!tabId) return
      let state = this.getAgentPptPlanningStateWithSystemSources()
      const outline = cloneArray(state.outline).sort((a, b) => (Number(a.pageNo || 0) || 0) - (Number(b.pageNo || 0) || 0))
      if (!outline.length || !cloneArray(state.narrativePlan && state.narrativePlan.slideRoles).length) return
      const writeRuntimeSlideState = (nextState) => {
        this.updateAgentPptPlanningTabRuntimeState(tabId, nextState)
      }
      const appendRuntimeSlideEvent = (name, details = {}) => {
        writeRuntimeSlideState(appendPptDebugEventToState(
          this.getAgentPptPlanningTabStateWithSystemSources(tabId),
          name,
          details,
        ))
      }
      writeRuntimeSlideState(startSlideGenerationQueue(state))
      const briefContext = this.buildAgentPptPlanningApiContext()
      for (;;) {
        state = this.getAgentPptPlanningTabStateWithSystemSources(tabId)
        if (!getAnalysisWorkspaceTabsFromState(this.ensureAgentTabs(false)).some((item) => asText(item && item.id) === tabId)) break
        const nextItem = cloneArray(state.slideGenerationQueue)
          .find((item) => String(item && item.status) !== 'ready')
        if (!nextItem) break
        const pageNo = Number(nextItem.pageNo || nextItem.page_no || 0) || 0
        const outlineItem = outline.find((item) => Number(item.pageNo || 0) === pageNo) || {}
        if (!pageNo) break
        const requestId = `slide-${pageNo}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
        writeRuntimeSlideState(markSlideRequestStarted(state, pageNo, requestId))
        state = this.getAgentPptPlanningTabStateWithSystemSources(tabId)
        try {
          appendRuntimeSlideEvent('slide_page_request_started', { pageNo, requestId, payloadSource: 'brief_context' })
          const response = await this.requestAgentPptPlanningDirectiveSlide(buildDeckBriefSlidePayload(
            state,
            { index: pageNo, title: outlineItem.theme, purpose: outlineItem.purpose },
            '按已确认目录和叙事方案生成这一页 brief。',
            briefContext,
          ), {
            onDebugEvent: (name, details = {}) => {
              appendRuntimeSlideEvent(`slide_${name}`, { pageNo, requestId, ...details })
            },
            timeoutMs: PPT_SLIDE_REQUEST_TIMEOUT_MS,
          })
          const responseIndex = Number(response && response.index || response && response.page_no || response && response.pageNo || 0) || 0
          const responseSummary = {
            responseIndex,
            responseKeys: Object.keys(response || {}).slice(0, 12),
            title: asText(response && response.title),
            hasKeyMessage: !!asText(response && (response.key_message || response.keyMessage)),
            visualSpecs: cloneArray(response && (response.visual_specs || response.visualSpecs)).length,
            metricClaims: cloneArray(response && (response.metric_claims || response.metricClaims)).length,
          }
          writeRuntimeSlideState(appendPptDebugEventToState(
            markSlideResponseReceived(
              this.getAgentPptPlanningTabStateWithSystemSources(tabId),
              pageNo,
              requestId,
              responseSummary,
            ),
            'slide_page_response_received',
            {
              pageNo,
              requestId,
              responseIndex,
              responseKeys: Object.keys(response || {}).slice(0, 12),
              payloadSummary: {
                title: asText(response && response.title),
                hasKeyMessage: !!asText(response && (response.key_message || response.keyMessage)),
                visualSpecs: cloneArray(response && (response.visual_specs || response.visualSpecs)).length,
                metricClaims: cloneArray(response && (response.metric_claims || response.metricClaims)).length,
              },
            },
          ))
          if (!responseIndex || responseIndex !== pageNo) {
            throw Object.assign(new Error('ppt_slide_response_index_mismatch'), {
              kind: 'invalid_slide_response',
              code: 'ppt_slide_response_index_mismatch',
              detail: { pageNo, responseIndex, requestId },
            })
          }
          writeRuntimeSlideState(markSlideApplying(
            this.getAgentPptPlanningTabStateWithSystemSources(tabId),
            pageNo,
            requestId,
          ))
          const beforeSlideCount = cloneArray((this.getAgentPptPlanningTabStateWithSystemSources(tabId).deckBrief || {}).slides).length
          const nextAppliedState = applySlideResponseAndMarkReady(
            this.getAgentPptPlanningTabStateWithSystemSources(tabId),
            pageNo,
            requestId,
            response,
          )
          const appliedSlides = cloneArray((nextAppliedState.deckBrief || {}).slides)
          if (!appliedSlides.some((slide) => Number(slide && slide.index || 0) === pageNo)) {
            throw Object.assign(new Error('ppt_slide_writeback_missing'), {
              kind: 'invalid_slide_writeback',
              code: 'ppt_slide_writeback_missing',
              detail: {
                pageNo,
                requestId,
                beforeSlideCount,
                afterSlideCount: appliedSlides.length,
                slideIndexes: appliedSlides.map((slide) => Number(slide && slide.index || 0) || 0).filter(Boolean),
              },
            })
          }
          const nextPage = cloneArray(nextAppliedState.slideGenerationQueue).find((item) => String(item && item.status) !== 'ready')
          this.updateAgentPptPlanningTabState(tabId, appendPptDebugEventToState(nextAppliedState, 'slide_page_applied', {
            pageNo,
            requestId,
            beforeSlideCount,
            afterSlideCount: appliedSlides.length,
            slideIndexes: appliedSlides.map((slide) => Number(slide.index || 0) || 0).filter(Boolean),
            nextPageNo: Number(nextPage && nextPage.pageNo || 0) || 0,
          }))
          const syncedState = this.getAgentPptPlanningTabState(tabId)
          const syncedSlides = cloneArray((syncedState.deckBrief || {}).slides)
          if (!syncedSlides.some((slide) => Number(slide && slide.index || 0) === pageNo)) {
            this.updateAgentPptPlanningTabState(tabId, appendPptDebugEventToState(
              nextAppliedState,
              'slide_writeback_recovered_after_sync',
              {
                pageNo,
                requestId,
                beforeSlideCount,
                afterSlideCount: appliedSlides.length,
                afterSyncSlideCount: syncedSlides.length,
                slideIndexes: appliedSlides.map((slide) => Number(slide && slide.index || 0) || 0).filter(Boolean),
              },
            ))
            const recoveredState = this.getAgentPptPlanningTabState(tabId)
            const recoveredSlides = cloneArray((recoveredState.deckBrief || {}).slides)
            if (recoveredSlides.some((slide) => Number(slide && slide.index || 0) === pageNo)) {
              continue
            }
            const error = Object.assign(new Error('ppt_slide_writeback_lost_after_sync'), {
              kind: 'invalid_slide_writeback',
              code: 'ppt_slide_writeback_lost_after_sync',
              detail: {
                pageNo,
                requestId,
                beforeSlideCount,
                afterSlideCount: appliedSlides.length,
                afterSyncSlideCount: syncedSlides.length,
                slideIndexes: syncedSlides.map((slide) => Number(slide && slide.index || 0) || 0).filter(Boolean),
              },
            })
            this.updateAgentPptPlanningTabState(tabId, appendPptDebugEventToState(
              markSlideFailed(
                this.getAgentPptPlanningTabStateWithSystemSources(tabId),
                pageNo,
                requestId,
                normalizePptGenerationErrorMessage(error, 'slides'),
                'writeback_lost',
              ),
              'slide_writeback_lost_after_sync',
              error.detail,
            ))
            break
          }
        } catch (error) {
          const detail = error && error.data && typeof error.data.detail === 'object' ? error.data.detail : null
          if (asText(error && error.code) === 'ppt_slide_request_timeout') {
            error.pageNo = pageNo
          }
          const failedWithEvent = appendPptDebugEventToState(
            this.getAgentPptPlanningTabStateWithSystemSources(tabId),
            'slide_page_request_failed',
            {
              pageNo,
              requestId,
              status: Number(error && error.status || 0) || 0,
              detailCode: asText(detail && detail.code),
              detailReason: asText(detail && detail.reason),
              errorCode: asText(error && error.code),
            },
          )
          const errorCode = asText(error && error.code)
          const errorKind = errorCode === 'ppt_slide_request_timeout'
            ? 'timeout'
            : errorCode === 'ppt_slide_response_index_mismatch'
              ? 'invalid_response'
              : errorCode === 'ppt_slide_writeback_missing'
                ? 'writeback_missing'
                : errorCode === 'ppt_slide_writeback_lost_after_sync'
                  ? 'writeback_lost'
                  : 'http_error'
          const failState = errorKind === 'timeout'
            ? markSlideTimedOut(failedWithEvent, pageNo, requestId, normalizePptGenerationErrorMessage(error, 'slides'))
            : markSlideFailed(failedWithEvent, pageNo, requestId, normalizePptGenerationErrorMessage(error, 'slides'), errorKind)
          this.updateAgentPptPlanningTabState(tabId, failState)
          break
        }
      }
    },
  }
}
