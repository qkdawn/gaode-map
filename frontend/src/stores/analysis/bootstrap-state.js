import { useAnalysisSessionStore } from './session'
import { useAnalysisPoiStore } from './poi'
import { useAnalysisH3Store } from './h3'
import { useAnalysisPopulationStore } from './population'
import { useAnalysisNightlightStore } from './nightlight'
import { useAnalysisGwrStore } from './gwr'
import { useAnalysisTimeseriesStore } from './timeseries'
import { useAnalysisRoadStore } from './road'
import { useAnalysisSharedGridStore } from './shared-grid'
import { useAnalysisExportStore } from './export'
import { useAnalysisHistoryStore } from './history'

export function createAnalysisInitialStateFromPinia(pinia, options = {}) {
  const {
    typeMapConfig = { groups: [] },
    roadSyntaxModulesReady = false,
    roadSyntaxModuleMissing = [],
    buildAnalysisPoiRuntimeInitialState = () => ({}),
    buildAnalysisPoiInitialState = () => ({}),
    buildAnalysisHistoryListInitialState = () => ({}),
    buildAnalysisHistoryInitialState = () => ({}),
    buildAnalysisH3InitialState = () => ({}),
    buildAnalysisPopulationInitialState = () => ({}),
    buildAnalysisNightlightInitialState = () => ({}),
    buildAnalysisGwrInitialState = () => ({}),
    buildAnalysisTimeseriesInitialState = () => ({}),
    buildAnalysisExportInitialState = () => ({}),
    buildRoadSyntaxInitialState = () => ({}),
    buildAnalysisSharedGridInitialState = () => ({}),
  } = options

  const sessionStore = useAnalysisSessionStore(pinia)
  const poiStore = useAnalysisPoiStore(pinia)
  const h3Store = useAnalysisH3Store(pinia)
  const populationStore = useAnalysisPopulationStore(pinia)
  const nightlightStore = useAnalysisNightlightStore(pinia)
  const gwrStore = useAnalysisGwrStore(pinia)
  const timeseriesStore = useAnalysisTimeseriesStore(pinia)
  const roadStore = useAnalysisRoadStore(pinia)
  const sharedGridStore = useAnalysisSharedGridStore(pinia)
  const exportStore = useAnalysisExportStore(pinia)
  const historyStore = useAnalysisHistoryStore(pinia)

  sessionStore.$reset()
  poiStore.$reset()
  h3Store.$reset()
  populationStore.$reset()
  nightlightStore.$reset()
  gwrStore.$reset()
  timeseriesStore.$reset()
  roadStore.$reset()
  sharedGridStore.$reset()
  exportStore.$reset()
  historyStore.$reset()

  poiStore.$patch({
    typeMapConfig,
    ...buildAnalysisPoiRuntimeInitialState(),
    ...buildAnalysisPoiInitialState(),
  })
  historyStore.$patch({
    ...buildAnalysisHistoryListInitialState(),
    ...buildAnalysisHistoryInitialState(),
  })
  h3Store.$patch(buildAnalysisH3InitialState())
  populationStore.$patch(buildAnalysisPopulationInitialState())
  nightlightStore.$patch(buildAnalysisNightlightInitialState())
  gwrStore.$patch(buildAnalysisGwrInitialState())
  timeseriesStore.$patch(buildAnalysisTimeseriesInitialState())
  roadStore.$patch({
    roadSyntaxModulesReady,
    roadSyntaxModuleMissing: Array.isArray(roadSyntaxModuleMissing)
      ? roadSyntaxModuleMissing.slice()
      : [],
    ...buildRoadSyntaxInitialState(),
  })
  exportStore.$patch(buildAnalysisExportInitialState())
  sharedGridStore.$patch(buildAnalysisSharedGridInitialState())

  const debugState = {
    isochroneDebugOpen: false,
    isLoadingIsochroneDebug: false,
    isochroneDebugSamplePoints: [],
    isochroneDebugFeatures: [],
    isochroneDebugErrors: [],
    isochroneDebugSelectedSampleId: '',
    isochroneDebugMarkers: [],
    isochroneDebugPolygons: [],
    isochroneDebugInfoWindow: null,
  }

  return Object.assign(
    {},
    poiStore.$state,
    debugState,
  )
}
