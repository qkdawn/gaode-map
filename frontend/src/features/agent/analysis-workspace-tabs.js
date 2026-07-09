import { cloneArray } from './normalizers.js'

export function getAnalysisWorkspaceTabsFromState(tabs = {}) {
  return cloneArray(tabs && tabs.analysisWorkspaceTabs)
}

export function withAnalysisWorkspaceTabs(tabs = {}, items = []) {
  const nextItems = cloneArray(items)
  return {
    ...tabs,
    analysisWorkspaceTabs: nextItems,
  }
}

export function cloneAgentTabsState(tabs = {}) {
  return withAnalysisWorkspaceTabs({
    ...tabs,
    summaryTabs: cloneArray(tabs.summaryTabs),
    iterationChangeTabs: cloneArray(tabs.iterationChangeTabs),
    siteSelectionTabs: cloneArray(tabs.siteSelectionTabs),
    followupTabs: cloneArray(tabs.followupTabs),
  }, getAnalysisWorkspaceTabsFromState(tabs))
}
