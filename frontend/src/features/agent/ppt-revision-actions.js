import { asText, cloneObject } from './normalizers.js'
import { normalizePptGenerationErrorMessage } from './ppt-generation-errors.js'
import {
  applyDeckBriefSlideRevision,
  applyPptOutlineSectionRevision,
  buildDeckBriefSlidePayload,
  buildPptOutlineSectionPayload,
  collectPptVisualArtifactFilenames,
  getPptRevisionKey,
  isPptDirectivePageStale,
  setPptActiveRevisionTarget,
  setPptGenerationError,
  setPptRevisionDraftField,
  setPptRevisionGeneratingTarget,
  undoPptSectionRevision,
} from '../ppt-planning/ui-state.js'

export function createAgentPptRevisionActionMethods() {
  return {
    openAgentPptPlanningRevisionTarget(type = '', target = {}) {
      this.updateAgentActivePptPlanningState(setPptActiveRevisionTarget(
        this.getAgentPptPlanningStateWithSystemSources(),
        { ...target, type },
      ))
    },
    closeAgentPptPlanningRevisionTarget() {
      this.updateAgentActivePptPlanningState(setPptActiveRevisionTarget(this.getAgentActivePptPlanningState(), {}))
    },
    updateAgentPptPlanningRevisionDraft(type = '', field = '', value = '') {
      this.updateAgentActivePptPlanningState(setPptRevisionDraftField(this.getAgentActivePptPlanningState(), type, field, value))
    },
    saveAgentPptPlanningRevision(type = '') {
      const state = this.getAgentActivePptPlanningState()
      const target = cloneObject(state.activeRevisionTarget)
      if (asText(type) === 'directive') {
        const draft = cloneObject(state.directiveRevisionDraft)
        const requiredSources = asText(draft.requiredSources)
          .split(/[,，\n]/)
          .map((item) => asText(item))
          .filter(Boolean)
        this.updateAgentActivePptPlanningState(applyDeckBriefSlideRevision(state, {
          index: Number(target.index || target.pageNo || 0) || 0,
          title: asText(draft.title),
          purpose: asText(draft.purpose),
          keyMessage: asText(draft.keyMessage),
          visualPlan: asText(draft.visualPlan),
          requiredSources,
        }))
        return
      }
      const draft = cloneObject(state.outlineRevisionDraft)
      this.updateAgentActivePptPlanningState(applyPptOutlineSectionRevision(state, {
        id: asText(target.id),
        pageNo: Number(target.pageNo || 0) || 0,
        theme: asText(draft.theme),
        purpose: asText(draft.purpose),
      }))
    },
    async regenerateAgentPptPlanningRevision(type = '') {
      const state = this.getAgentPptPlanningStateWithSystemSources()
      const target = cloneObject(state.activeRevisionTarget)
      const normalizedType = asText(type)
      const draft = normalizedType === 'directive' ? cloneObject(state.directiveRevisionDraft) : cloneObject(state.outlineRevisionDraft)
      const revisionNote = asText(draft.revisionNote)
      if (!target.type || !revisionNote) return
      this.updateAgentActivePptPlanningState(setPptRevisionGeneratingTarget(state, target))
      try {
        if (normalizedType === 'directive') {
          const context = await this.buildAgentPptPlanningVisualApiContext()
          const staleFilenames = collectPptVisualArtifactFilenames(state.deckBrief.slides
            .filter((slide) => Number(slide.index || 0) === Number(target.index || target.pageNo || 0)))
          const response = await this.requestAgentPptPlanningDirectiveSlide(buildDeckBriefSlidePayload(state, target, revisionNote, context))
          this.updateAgentActivePptPlanningState(applyDeckBriefSlideRevision(this.getAgentActivePptPlanningState(), response))
          this.cleanupAgentPptPlanningVisualArtifacts(staleFilenames)
          return
        }
        const context = this.buildAgentPptPlanningApiContext()
        const response = await this.requestAgentPptPlanningOutlineSection(buildPptOutlineSectionPayload(state, target, revisionNote, context))
        this.updateAgentActivePptPlanningState(applyPptOutlineSectionRevision(this.getAgentActivePptPlanningState(), response))
      } catch (error) {
        const errorSource = normalizedType === 'directive' ? 'directive' : 'outline'
        this.updateAgentActivePptPlanningState(setPptGenerationError(
          this.getAgentActivePptPlanningState(),
          normalizePptGenerationErrorMessage(error, errorSource),
          errorSource,
        ))
      }
    },
    undoAgentPptPlanningRevision(type = '', target = {}) {
      this.updateAgentActivePptPlanningState(undoPptSectionRevision(this.getAgentActivePptPlanningState(), type, target))
    },
    hasAgentPptPlanningRevisionSnapshot(type = '', target = {}) {
      const state = this.getAgentActivePptPlanningState()
      const key = getPptRevisionKey(type, target)
      return !!(key && state.revisionSnapshots && state.revisionSnapshots[key])
    },
    isAgentPptPlanningDirectivePageStale(pageNo = 0) {
      return isPptDirectivePageStale(this.getAgentActivePptPlanningState(), pageNo)
    },
  }
}
