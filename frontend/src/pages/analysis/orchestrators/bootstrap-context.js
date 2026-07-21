import { createPinia } from 'pinia'
import { createAnalysisWorkbenchMethods } from '../../../features/workbench/navigation'
import { createAnalysisWorkbenchSessionMethods } from '../../../features/workbench/session'
import { createAnalysisIsochroneMethods } from '../../../features/isochrone/runtime'
import { createAnalysisPoiInitialState, createAnalysisPoiPanelMethods } from '../../../features/poi/panel'
import { createAnalysisPoiRuntimeInitialState, createAnalysisPoiRuntimeMethods } from '../../../features/poi/runtime'
import { createAnalysisHistoryListInitialState, createAnalysisHistoryListMethods } from '../../../features/history/list'
import { createAnalysisHistoryInitialState, createAnalysisHistoryMethods } from '../../../features/history/restore'
import { createAnalysisH3InitialState, createAnalysisH3Methods } from '../../../features/h3/panel'
import { createAnalysisPopulationInitialState, createAnalysisPopulationMethods } from '../../../features/population/panel'
import { createAnalysisNightlightInitialState, createAnalysisNightlightMethods } from '../../../features/nightlight/panel'
import { createAnalysisGwrInitialState, createAnalysisGwrMethods } from '../../../features/gwr/panel'
import { createAnalysisTimeseriesInitialState, createAnalysisTimeseriesMethods } from '../../../features/timeseries/panel'
import { createAnalysisSharedGridMethods } from '../../../features/shared-grid/panel'
import { createAnalysisSharedGridInitialState } from '../../../features/shared-grid/state'
import { createAnalysisExportInitialState, createAnalysisExportMethods } from '../../../features/export/export-bundle'
import { createRoadSyntaxUiMethods } from '../../../features/road/ui'
import { createRoadSyntaxControllerCoreMethods } from '../../../features/road/controller-core'
import { createRoadSyntaxWebGLMethods } from '../../../features/road/webgl'
import { createRoadSyntaxInitialState } from '../../../features/road/state'
import { createRoadSyntaxOverlayCommitMethods } from '../../../map/overlay-committer'
import { createMapWriteQueue } from '../../../map/map-write-queue'
import { createAnalysisInitialStateFromPinia } from '../../../stores/analysis/bootstrap-state'
import { useAnalysisSessionStore, ANALYSIS_SESSION_STATE_KEYS } from '../../../stores/analysis/session'
import { useAnalysisHistoryStore, ANALYSIS_HISTORY_STATE_KEYS } from '../../../stores/analysis/history'
import { useAnalysisH3Store, ANALYSIS_H3_STATE_KEYS } from '../../../stores/analysis/h3'
import { useAnalysisPopulationStore, ANALYSIS_POPULATION_STATE_KEYS } from '../../../stores/analysis/population'
import { useAnalysisNightlightStore, ANALYSIS_NIGHTLIGHT_STATE_KEYS } from '../../../stores/analysis/nightlight'
import { useAnalysisGwrStore, ANALYSIS_GWR_STATE_KEYS } from '../../../stores/analysis/gwr'
import { useAnalysisTimeseriesStore, ANALYSIS_TIMESERIES_STATE_KEYS } from '../../../stores/analysis/timeseries'
import { useAnalysisExportStore, ANALYSIS_EXPORT_STATE_KEYS } from '../../../stores/analysis/export'
import { useAnalysisRoadStore, ANALYSIS_ROAD_STATE_KEYS } from '../../../stores/analysis/road'
import { useAnalysisSharedGridStore, ANALYSIS_SHARED_GRID_STATE_KEYS } from '../../../stores/analysis/shared-grid'
import { createStoreBackedComputed } from '../adapters/store-computed-bridge'
import { createAnalysisPoiMapVisibilityAdapterMethods } from '../adapters/poi-map-visibility'
import { createAnalysisMapOrchestratorMethods } from './map'
import { createAnalysisHistoryOrchestratorMethods } from './history'
import { createAnalysisExportOrchestratorMethods } from './export'
import { createAnalysisPoiFlowOrchestratorMethods } from './poi-flow'

function createRoadSyntaxConst() {
  return Object.freeze({
    SWITCH_TARGET_MS: 120,
    PREBUILD_DEADLINE_MS: 120000,
    CONNECTIVITY_NODE_MIN_ZOOM: 15,
    SWITCH_SAMPLE_LIMIT: 40,
    BUILD_BUDGET_MS: Object.freeze({
      interacting: 0.8,
      init: 6.0,
      steady: 4.0,
      lineFallbackSmall: 12.0,
      lineFallbackLarge: 8.0,
      node: 6.5,
    }),
  })
}

function createAnalysisBootstrapContext(options = {}) {
  const typeMapConfig = (options && options.typeMapConfig) || { groups: [] }
  const roadSyntaxConst = createRoadSyntaxConst()

  const analysisWorkbenchMethods = createAnalysisWorkbenchMethods()
  const analysisWorkbenchSessionMethods = createAnalysisWorkbenchSessionMethods()
  const isochroneMethods = createAnalysisIsochroneMethods()
  const buildAnalysisPoiInitialState = () => createAnalysisPoiInitialState()
  const buildAnalysisPoiRuntimeInitialState = () => createAnalysisPoiRuntimeInitialState()
  const poiPanelMethods = createAnalysisPoiPanelMethods()
  const poiRuntimeMethods = createAnalysisPoiRuntimeMethods()
  const buildAnalysisHistoryListInitialState = () => createAnalysisHistoryListInitialState()
  const buildAnalysisHistoryInitialState = () => createAnalysisHistoryInitialState()
  const historyListMethods = createAnalysisHistoryListMethods()
  const historyMethods = createAnalysisHistoryMethods()
  const buildAnalysisH3InitialState = () => createAnalysisH3InitialState()
  const h3Methods = createAnalysisH3Methods()
  const buildAnalysisPopulationInitialState = () => createAnalysisPopulationInitialState()
  const populationMethods = createAnalysisPopulationMethods()
  const buildAnalysisNightlightInitialState = () => createAnalysisNightlightInitialState()
  const nightlightMethods = createAnalysisNightlightMethods()
  const buildAnalysisGwrInitialState = () => createAnalysisGwrInitialState()
  const gwrMethods = createAnalysisGwrMethods()
  const buildAnalysisTimeseriesInitialState = () => createAnalysisTimeseriesInitialState()
  const timeseriesMethods = createAnalysisTimeseriesMethods()
  const buildAnalysisExportInitialState = () => createAnalysisExportInitialState()
  const buildAnalysisSharedGridInitialState = () => createAnalysisSharedGridInitialState()
  const sharedGridMethods = createAnalysisSharedGridMethods()
  const exportMethods = createAnalysisExportMethods()
  const roadSyntaxUiMethods = createRoadSyntaxUiMethods(roadSyntaxConst)
  const roadSyntaxOverlayCommitMethods = createRoadSyntaxOverlayCommitMethods(roadSyntaxConst)
  const roadSyntaxControllerCoreMethods = createRoadSyntaxControllerCoreMethods(roadSyntaxConst)
  const roadSyntaxWebglMethods = createRoadSyntaxWebGLMethods(roadSyntaxConst)
  const buildRoadSyntaxInitialState = () => createRoadSyntaxInitialState(roadSyntaxConst)
  const mapOrchestratorMethods = createAnalysisMapOrchestratorMethods()
  const historyOrchestratorMethods = createAnalysisHistoryOrchestratorMethods()
  const exportOrchestratorMethods = createAnalysisExportOrchestratorMethods()
  const poiFlowOrchestratorMethods = createAnalysisPoiFlowOrchestratorMethods()
  const poiMapVisibilityAdapterMethods = createAnalysisPoiMapVisibilityAdapterMethods()

  const roadSyntaxModuleRequirements = Object.freeze({
    queue: typeof createMapWriteQueue === 'function',
    overlayCommit: typeof createRoadSyntaxOverlayCommitMethods === 'function',
    state: typeof createRoadSyntaxInitialState === 'function',
    controller: typeof createRoadSyntaxControllerCoreMethods === 'function',
    ui: typeof createRoadSyntaxUiMethods === 'function',
  })
  const roadSyntaxModuleMissing = Object.keys(roadSyntaxModuleRequirements).filter(
    (key) => !roadSyntaxModuleRequirements[key],
  )
  const roadSyntaxModulesReady = roadSyntaxModuleMissing.length === 0
  if (!roadSyntaxModulesReady) {
    console.error('[road-syntax] module wiring incomplete', {
      missing: roadSyntaxModuleMissing.slice(),
      static_version: 'frontend-build',
    })
  }

  const pinia = createPinia()
  const initialState = createAnalysisInitialStateFromPinia(pinia, {
    typeMapConfig,
    roadSyntaxModulesReady,
    roadSyntaxModuleMissing: roadSyntaxModuleMissing.slice(),
    buildAnalysisPoiRuntimeInitialState,
    buildAnalysisPoiInitialState,
    buildAnalysisHistoryListInitialState,
    buildAnalysisHistoryInitialState,
    buildAnalysisH3InitialState,
    buildAnalysisPopulationInitialState,
    buildAnalysisNightlightInitialState,
    buildAnalysisGwrInitialState,
    buildAnalysisTimeseriesInitialState,
    buildAnalysisExportInitialState,
    buildAnalysisSharedGridInitialState,
    buildRoadSyntaxInitialState,
  })

  const sessionStore = useAnalysisSessionStore(pinia)
  const historyStore = useAnalysisHistoryStore(pinia)
  const h3Store = useAnalysisH3Store(pinia)
  const populationStore = useAnalysisPopulationStore(pinia)
  const nightlightStore = useAnalysisNightlightStore(pinia)
  const gwrStore = useAnalysisGwrStore(pinia)
  const timeseriesStore = useAnalysisTimeseriesStore(pinia)
  const exportStore = useAnalysisExportStore(pinia)
  const roadStore = useAnalysisRoadStore(pinia)
  const sharedGridStore = useAnalysisSharedGridStore(pinia)
  const storeBackedComputed = createStoreBackedComputed([
    { store: sessionStore, fieldKeys: ANALYSIS_SESSION_STATE_KEYS },
    { store: historyStore, fieldKeys: ANALYSIS_HISTORY_STATE_KEYS },
    { store: h3Store, fieldKeys: ANALYSIS_H3_STATE_KEYS },
    { store: populationStore, fieldKeys: ANALYSIS_POPULATION_STATE_KEYS },
    { store: nightlightStore, fieldKeys: ANALYSIS_NIGHTLIGHT_STATE_KEYS },
    { store: gwrStore, fieldKeys: ANALYSIS_GWR_STATE_KEYS },
    { store: timeseriesStore, fieldKeys: ANALYSIS_TIMESERIES_STATE_KEYS },
    { store: exportStore, fieldKeys: ANALYSIS_EXPORT_STATE_KEYS },
    { store: roadStore, fieldKeys: ANALYSIS_ROAD_STATE_KEYS },
    { store: sharedGridStore, fieldKeys: ANALYSIS_SHARED_GRID_STATE_KEYS },
  ])

  return {
    pinia,
    initialState,
    storeBackedComputed,
    roadSyntaxModulesReady,
    roadSyntaxModuleMissing,
    methods: {
      analysisWorkbenchMethods,
      analysisWorkbenchSessionMethods,
      isochroneMethods,
      poiPanelMethods,
      poiRuntimeMethods,
      historyListMethods,
      historyMethods,
      h3Methods,
      populationMethods,
      nightlightMethods,
      gwrMethods,
      timeseriesMethods,
      sharedGridMethods,
      exportMethods,
      roadSyntaxOverlayCommitMethods,
      roadSyntaxControllerCoreMethods,
      roadSyntaxWebglMethods,
      roadSyntaxUiMethods,
      mapOrchestratorMethods,
      historyOrchestratorMethods,
      exportOrchestratorMethods,
      poiFlowOrchestratorMethods,
      poiMapVisibilityAdapterMethods,
    },
  }
}

export { createAnalysisBootstrapContext }
