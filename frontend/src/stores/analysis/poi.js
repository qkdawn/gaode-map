import { defineStore } from 'pinia'

export const useAnalysisPoiStore = defineStore('analysis_poi', {
  state: () => ({
    poiKeywords: '',
    typeMapConfig: { groups: [] },
    step3NavItems: [
      { id: 'poi', label: 'POI', title: 'POI 点数据分析' },
      { id: 'population', label: '人口', title: '人口格网分析' },
      { id: 'nightlight', label: '夜光', title: '夜光格网分析' },
      { id: 'gwr', label: 'GWR', title: '夜光地理加权回归' },
      { id: 'timeseries', label: '时序', title: '人口与夜光时序变化' },
      { id: 'syntax', label: '路网', title: '路网分析' },
      { id: 'agent', label: 'AI', title: 'AI Agent 区域报告' },
    ],
    activeStep3Panel: 'poi',
    lastNonAgentStep3Panel: 'poi',
    isStep3SidebarCollapsed: false,
    dragIndex: null,
    dragOverIndex: null,
    dragInsertPosition: null,
    isDraggingNav: false,
    isFetchingPois: false,
    fetchProgress: 0,
    poiStatus: '',
    poiFetchErrors: [],
    pointSimplifyEnabled: false,
    pointLayersSuspendedForSyntax: false,
    poiSystemSuspendedForSyntax: false,
  }),
})

export {}
