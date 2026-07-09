import { asText, cloneArray, cloneObject } from './normalizers.js'
import { normalizePptGenerationErrorMessage } from './ppt-generation-errors.js'
import { isPptCarrierSnapshotRequest } from '../ppt-planning/carrier-snapshot.js'
import { isPptMapSnapshotRequest } from '../ppt-planning/map-snapshot.js'
import {
  applyPptVisualArtifactsResponse,
  buildPptVisualArtifactsPayload,
  clearPptSlideMapSnapshotCaptureErrors,
  failPptVisualArtifacts,
  startPptVisualArtifactsGeneration,
} from '../ppt-planning/ui-state.js'

export function createAgentPptVisualGenerationMethods() {
  return {
    async generateAgentPptPlanningSlideVisuals(slideIndex = 0) {
      const activeTab = this.getAgentActivePptPlanningTab()
      const tabId = asText(activeTab && activeTab.id)
      const index = Number(slideIndex || 0) || 0
      if (!tabId || !index) return
      let state = this.getAgentPptPlanningTabStateWithSystemSources(tabId)
      let slide = cloneArray((state.deckBrief || {}).slides).find((item) => Number(item.index || 0) === index)
      if (!slide || !cloneArray(slide.visualSpecs).length) return
      state = clearPptSlideMapSnapshotCaptureErrors(state, index)
      slide = cloneArray((state.deckBrief || {}).slides).find((item) => Number(item.index || 0) === index) || slide
      this.updateAgentPptPlanningTabState(tabId, startPptVisualArtifactsGeneration(state, index))
      try {
        const initialPayload = buildPptVisualArtifactsPayload(
          this.getAgentPptPlanningTabStateWithSystemSources(tabId),
          slide,
          await this.buildAgentPptPlanningVisualApiContext(),
        )
        let response = await this.requestAgentPptPlanningVisualArtifacts(initialPayload)
        const mapRequestSpecs = cloneArray(response && (response.visual_specs || response.visualSpecs))
          .filter((visual) => isPptMapSnapshotRequest(visual) || isPptCarrierSnapshotRequest(visual))
        if (mapRequestSpecs.length && typeof this.captureAgentPptMapRequestAssets === 'function') {
          try {
            const captureResult = await this.captureAgentPptMapRequestAssets(mapRequestSpecs)
            const capturedAssets = Array.isArray(captureResult)
              ? captureResult
              : cloneArray(captureResult && captureResult.assets)
            const capturedVisualSpecs = Array.isArray(captureResult)
              ? mapRequestSpecs.map((item) => cloneObject(item))
              : cloneArray(captureResult && (captureResult.visualSpecs || captureResult.visual_specs))
            if (capturedVisualSpecs.length) {
              response = {
                ...cloneObject(response),
                visual_specs: cloneArray(response && (response.visual_specs || response.visualSpecs)).map((visual) => {
                  const visualId = asText(visual && (visual.visual_id || visual.visualId))
                  const captured = capturedVisualSpecs.find((item) => asText(item && (item.visual_id || item.visualId)) === visualId)
                  return captured ? cloneObject(captured) : cloneObject(visual)
                }),
              }
            }
            if (capturedAssets.length) {
              response = await this.requestAgentPptPlanningVisualArtifacts({
                ...initialPayload,
                visual_specs: capturedVisualSpecs.length
                  ? capturedVisualSpecs.map((item) => cloneObject(item))
                  : mapRequestSpecs.map((item) => cloneObject(item)),
                existing_assets: [
                  ...cloneArray(initialPayload.existing_assets).map((item) => cloneObject(item)),
                  ...capturedAssets,
                ],
              })
            }
          } catch (captureError) {
            if (typeof console !== 'undefined' && console.warn) {
              console.warn('PPT map snapshot request capture failed; keeping needs_existing_asset state', captureError)
            }
          }
        }
        this.updateAgentPptPlanningTabState(tabId, applyPptVisualArtifactsResponse(
          this.getAgentPptPlanningTabStateWithSystemSources(tabId),
          response,
        ))
      } catch (error) {
        this.updateAgentPptPlanningTabState(tabId, failPptVisualArtifacts(
          this.getAgentPptPlanningTabStateWithSystemSources(tabId),
          index,
          normalizePptGenerationErrorMessage(error, 'visuals'),
        ))
      }
    },
    async generateAgentPptPlanningAllVisuals() {
      const activeTab = this.getAgentActivePptPlanningTab()
      const tabId = asText(activeTab && activeTab.id)
      if (!tabId) return
      const initialState = this.getAgentPptPlanningTabStateWithSystemSources(tabId)
      const slides = cloneArray((initialState.deckBrief || {}).slides)
        .filter((slide) => cloneArray(slide.visualSpecs).length)
        .sort((left, right) => (Number(left.index || 0) || 0) - (Number(right.index || 0) || 0))
      if (!slides.length) return
      for (const slide of slides) {
        await this.generateAgentPptPlanningSlideVisuals(Number(slide.index || 0) || 0)
      }
    },
  }
}
