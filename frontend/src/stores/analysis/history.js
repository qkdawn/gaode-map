import { defineStore } from 'pinia'

export const ANALYSIS_HISTORY_STATE_KEYS = Object.freeze([
  'historyListRaw',
  'historyList',
  'historyLoading',
  'historyLoadedCount',
  'historySkeletonCount',
  'historyHasLoadedOnce',
  'historyRenderSessionId',
  'historyRenderRafId',
  'historyFetchAbortController',
  'isSelectionMode',
  'selectedHistoryIds',
  'historyDetailAbortController',
  'historyPoiAbortController',
  'historyArtifactsAbortController',
  'historyDetailLoadToken',
  'currentHistoryRecordId',
  'currentHistoryPolygonWgs84',
])

export function createAnalysisHistoryInitialState() {
  return {
    historyListRaw: [],
    historyList: [],
    historyLoading: false,
    historyLoadedCount: 0,
    historySkeletonCount: 5,
    historyHasLoadedOnce: false,
    historyRenderSessionId: 0,
    historyRenderRafId: null,
    historyFetchAbortController: null,
    isSelectionMode: false,
    selectedHistoryIds: [],
    historyDetailAbortController: null,
    historyPoiAbortController: null,
    historyArtifactsAbortController: null,
    historyDetailLoadToken: 0,
    currentHistoryRecordId: '',
    currentHistoryPolygonWgs84: [],
  }
}

export const useAnalysisHistoryStore = defineStore('analysis_history', {
  state: () => createAnalysisHistoryInitialState(),
})
