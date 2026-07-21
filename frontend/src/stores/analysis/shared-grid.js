import { defineStore } from 'pinia'
import { createAnalysisSharedGridInitialState } from '../../features/shared-grid/state'

export { createAnalysisSharedGridInitialState }

export const ANALYSIS_SHARED_GRID_STATE_KEYS = Object.freeze(
  Object.keys(createAnalysisSharedGridInitialState()),
)

export const useAnalysisSharedGridStore = defineStore('analysis_shared_grid', {
  state: () => createAnalysisSharedGridInitialState(),
})