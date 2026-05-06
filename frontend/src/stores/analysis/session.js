import { defineStore } from 'pinia'

export const ANALYSIS_SESSION_STATE_KEYS = Object.freeze([
  'step',
  'sidebarView',
  'historyReturnContext',
  'selectedPoint',
  'transportMode',
  'timeHorizon',
  'isochroneScopeMode',
  'poiYearSource',
  'poiYearSelections',
  'resultPoiYear',
  'poiDataSource',
  'resultDataSource',
  'isCalculating',
  'errorMessage',
  'basemapSource',
  'tdtDiag',
  'tdtDiagCopyStatus',
  'scopeSource',
  'drawnScopePolygon',
  'lastIsochroneGeoJSON',
  'abortController',
])

export function createAnalysisSessionInitialState() {
  return {
    step: 1,
    sidebarView: 'start',
    historyReturnContext: null,
    selectedPoint: null,
    transportMode: 'walking',
    timeHorizon: 15,
    isochroneScopeMode: 'point',
    poiYearSource: '2020',
    poiYearSelections: [2020, 2022, 2024],
    resultPoiYear: 2020,
    poiDataSource: 'local',
    resultDataSource: 'local',
    isCalculating: false,
    errorMessage: '',
    basemapSource: 'amap',
    tdtDiag: null,
    tdtDiagCopyStatus: '',
    scopeSource: '',
    drawnScopePolygon: [],
    lastIsochroneGeoJSON: null,
    abortController: null,
  }
}

export const useAnalysisSessionStore = defineStore('analysis_session', {
  state: () => createAnalysisSessionInitialState(),
})
