import { defineStore } from 'pinia'
import {
  createAnalysisHistoryListInitialState,
} from '../../features/history/list.js'
import {
  createAnalysisHistoryInitialState as createHistoryRestoreInitialState,
} from '../../features/history/restore.js'

export function createAnalysisHistoryInitialState() {
  return {
    ...createAnalysisHistoryListInitialState(),
    ...createHistoryRestoreInitialState(),
  }
}

export const ANALYSIS_HISTORY_STATE_KEYS = Object.freeze(
  Object.keys(createAnalysisHistoryInitialState()),
)

export const useAnalysisHistoryStore = defineStore('analysis_history', {
  state: () => createAnalysisHistoryInitialState(),
})
