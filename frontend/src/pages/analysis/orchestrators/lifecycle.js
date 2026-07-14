function createAnalysisLifecycleHooks(options = {}) {
  const roadSyntaxModulesReady = !!options.roadSyntaxModulesReady
  const roadSyntaxModuleMissing = Array.isArray(options.roadSyntaxModuleMissing)
    ? options.roadSyntaxModuleMissing
    : []

  return {
    async mounted() {
      if (typeof window !== 'undefined') {
        window.addEventListener('resize', this.resizeAnalysisMap)
      }
      try {
        this.config = (window.__ANALYSIS_BOOTSTRAP__ && window.__ANALYSIS_BOOTSTRAP__.config)
          ? window.__ANALYSIS_BOOTSTRAP__.config
          : { amap_js_api_key: '', amap_js_security_code: '', tianditu_key: '' }
        this.initializePoiCategoriesFromTypeMap()
        if (this.basemapSource === 'tianditu') {
          const tileReady = await this.validateTiandituSource()
          if (!tileReady) {
            this.tdtDiagCopyStatus = ''
          }
        }

        const amapTimeoutMs = 8000
        await Promise.race([
          this.loadAMapScript(this.config.amap_js_api_key, this.config.amap_js_security_code),
          new Promise((_, reject) => setTimeout(() => reject(new Error('AMap 加载超时，请检查网络或 Key')), amapTimeoutMs)),
        ])

        this.initMap()
        this.resizeAnalysisMap()
      } catch (e) {
        console.error('Initialization Failed:', e)
        this.errorMessage = '系统初始化失败: ' + e.message
      } finally {
        this.preloadHistoryListInBackground()
        if (!roadSyntaxModulesReady) {
          this.roadSyntaxSetStatus(`路网模块未完整加载：${roadSyntaxModuleMissing.join(', ')}`)
        }
        this.attachAmapRuntimeErrorProbe()
        document.addEventListener('click', this.handleGlobalClick, true)
        this.loadingConfig = false
        const overlay = document.getElementById('loading-overlay')
        if (overlay) overlay.style.display = 'none'
      }
    },
      beforeUnmount() {
      document.removeEventListener('click', this.handleGlobalClick, true)
      this.detachAmapRuntimeErrorProbe()
      this.destroyPlaceSearch()
      this.stopScopeDrawing({ destroyTool: true })
      this.clearPoiOverlayLayers({
        reason: 'before_unmount',
        clearManager: true,
        clearSimpleMarkers: true,
        clearCenterMarker: true,
        resetFilterPanel: true,
        immediate: true,
      })
      this.clearPoiKdeOverlay()
      this.roadSyntaxDetachMapListeners()
      if (typeof this.cancelRoadSyntaxRequest === 'function') {
        this.cancelRoadSyntaxRequest('before_unmount')
      }
      this.invalidateRoadSyntaxCache('unmount', { resetData: true })
      if (this.h3ToastTimer) {
        clearTimeout(this.h3ToastTimer)
        this.h3ToastTimer = null
      }
      this.cancelHistoryLoading()
      this.cancelHistoryDetailLoading()
      this.disposePoiChart()
      this.disposeH3Charts()
      this.disposePopulationCharts()
      if (typeof this.disposeGwrCharts === 'function') this.disposeGwrCharts()
      this.clearPopulationRasterDisplayOnLeave()
      this.clearNightlightDisplayOnLeave()
      if (typeof this.clearGwrDisplayOnLeave === 'function') this.clearGwrDisplayOnLeave()
      if (typeof this.destroyAllAgentRuns === 'function') {
        this.destroyAllAgentRuns()
      }
      if (typeof window !== 'undefined') {
        window.removeEventListener('resize', this.resizeAnalysisMap)
      }
    },
    watch: {
      'agentPanelPayloads.analysis_run.run_id'(newRunId, oldRunId) {
        if (String(newRunId || '') === String(oldRunId || '')) return
        if (typeof this.resetStage1SpatialInteraction === 'function') {
          this.resetStage1SpatialInteraction()
        }
      },
      step(newStep, oldStep) {
        if (oldStep === 1 && newStep !== 1) {
          this.destroyPlaceSearch()
          this.stopScopeDrawing()
        }
      },
      sidebarView(newView, oldView) {
        if (oldView === 'history' && newView !== 'history') {
          this.cancelHistoryLoading()
        }
        if (oldView === 'wizard' && newView !== 'wizard') {
          this.stopScopeDrawing()
        }
        this.resizeAnalysisMap()
      },
      activeStep3Panel(newPanel, oldPanel) {
        if (newPanel === oldPanel) return
        if (typeof this.autoEnableDisplayTargetsForPanel === 'function') {
          this.autoEnableDisplayTargetsForPanel(newPanel)
        }
        const syntaxEnabled = (typeof this.hasSimplifyDisplayTarget === 'function')
          && this.hasSimplifyDisplayTarget('syntax')
        if (newPanel === 'syntax' || syntaxEnabled) {
          if (typeof this.resumeRoadSyntaxDisplay === 'function') {
            this.resumeRoadSyntaxDisplay()
          }
        } else if (typeof this.suspendRoadSyntaxDisplay === 'function') {
          this.suspendRoadSyntaxDisplay()
        }
        const poiEnabled = (typeof this.hasSimplifyDisplayTarget === 'function')
          && this.hasSimplifyDisplayTarget('poi')
        if (newPanel === 'syntax' && !poiEnabled) {
          this.suspendPoiSystemForSyntax()
        } else if (oldPanel === 'syntax') {
          this.resumePoiSystemAfterSyntax()
        }
        const populationEnabled = (typeof this.hasSimplifyDisplayTarget === 'function')
          && this.hasSimplifyDisplayTarget('population')
        if (oldPanel === 'population' && newPanel !== 'population' && !populationEnabled) {
          this.clearPopulationRasterDisplayOnLeave()
        }
        const nightlightEnabled = (typeof this.hasSimplifyDisplayTarget === 'function')
          && this.hasSimplifyDisplayTarget('nightlight')
        if (oldPanel === 'nightlight' && newPanel !== 'nightlight' && !nightlightEnabled) {
          this.clearNightlightDisplayOnLeave()
        }
        const gwrEnabled = (typeof this.hasSimplifyDisplayTarget === 'function')
          && this.hasSimplifyDisplayTarget('gwr')
        if (oldPanel === 'gwr' && newPanel !== 'gwr' && !gwrEnabled) {
          this.clearGwrDisplayOnLeave()
        }
        const timeseriesEnabled = (typeof this.hasSimplifyDisplayTarget === 'function')
          && this.hasSimplifyDisplayTarget('timeseries')
        if (oldPanel === 'timeseries' && newPanel !== 'timeseries' && !timeseriesEnabled) {
          if (typeof this.clearTimeseriesDisplayOnLeave === 'function') this.clearTimeseriesDisplayOnLeave()
        }
        if (newPanel === 'population') {
          this.ensurePopulationPanelEntryState()
        }
        if (newPanel === 'nightlight') {
          this.ensureNightlightPanelEntryState()
        }
        if (newPanel === 'gwr') {
          this.ensureGwrPanelEntryState()
        }
        if (newPanel === 'timeseries') {
          if (typeof this.ensureTimeseriesPanelEntryState === 'function') this.ensureTimeseriesPanelEntryState()
        }
        this.$nextTick(() => {
          this.refreshPoiKdeOverlay()
          this.applySimplifyConfig()
        })
      },
      roadSyntaxGraphModel(newModel, oldModel) {
        const nextModel = String(newModel || '').trim().toLowerCase()
        const prevModel = String(oldModel || '').trim().toLowerCase()
        if (!prevModel || nextModel === prevModel) return
        this.roadSyntaxSetStatus(`图模型已切换为${this.roadSyntaxGraphModelLabel(nextModel)}，请重新计算路网指标`)
      },
    },
  }
}

export { createAnalysisLifecycleHooks }
