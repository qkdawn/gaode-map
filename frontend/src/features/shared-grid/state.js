export function createAnalysisSharedGridInitialState() {
  return {
    isGeneratingSharedGrid: false,
    sharedGridStatus: '',
    sharedGrid: null,
    sharedGridSummary: {},
    sharedGridSourceVersions: {},
    sharedGridSourceReadiness: {},
    sharedGridLimitations: [],
    sharedGridMetric: 'density_poi_per_km2',
    sharedGridSelectedCellId: '',
  }
}