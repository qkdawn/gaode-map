function createAnalysisHistoryOrchestratorMethods() {
  return {
    cancelHistoryDetailLoading() {
      if (this.historyDetailAbortController) {
        try {
          this.historyDetailAbortController.abort()
        } catch (e) {
          console.warn('history detail abort failed', e)
        }
        this.historyDetailAbortController = null
      }
      this.historyDetailLoadToken += 1
    },
    buildHistoryH3ResultSnapshot() {
      const analysisFeatures = Array.isArray(this.h3AnalysisGridFeatures)
        ? this.h3AnalysisGridFeatures
        : []
      const plainFeatures = Array.isArray(this.h3GridFeatures) ? this.h3GridFeatures : []
      const features = analysisFeatures.length ? analysisFeatures : plainFeatures
      const hasData = features.length > 0 || !!this.h3AnalysisSummary
      if (!hasData) return null

      const countRaw = Number(this.h3GridCount)
      return {
        grid: {
          type: 'FeatureCollection',
          features,
          count: Number.isFinite(countRaw) ? countRaw : features.length,
          resolution: Number(this.h3GridResolution) || 10,
          include_mode: String(this.h3GridIncludeMode || 'intersects'),
          min_overlap_ratio: Number(this.h3GridMinOverlapRatio) || 0,
        },
        summary: this.h3AnalysisSummary || null,
        charts: this.h3AnalysisCharts || null,
        ui: {
          main_stage: String(this.h3MainStage || 'params'),
          sub_tab: String(this.h3SubTab || 'metric_map'),
          metric_view: String(this.h3MetricView || 'density'),
          structure_fill_mode: String(this.h3StructureFillMode || 'gi_z'),
          panel_active: this.activeStep3Panel === 'poi'
            && String(this.poiSubTab || '').trim().toLowerCase() === 'grid',
        },
      }
    },
    buildHistoryRoadResultSnapshot() {
      const roadFeatures = Array.isArray(this.roadSyntaxRoadFeatures)
        ? this.roadSyntaxRoadFeatures
        : []
      const nodeFeatures = Array.isArray(this.roadSyntaxNodes) ? this.roadSyntaxNodes : []
      const hasData = roadFeatures.length > 0 || nodeFeatures.length > 0 || !!this.roadSyntaxSummary
      if (!hasData) return null

      return {
        summary: this.roadSyntaxSummary || null,
        diagnostics: this.roadSyntaxDiagnostics || null,
        roads: {
          type: 'FeatureCollection',
          features: roadFeatures,
          count: roadFeatures.length,
        },
        nodes: {
          type: 'FeatureCollection',
          features: nodeFeatures,
          count: nodeFeatures.length,
        },
        webgl: this.roadSyntaxWebglPayload || null,
        ui: {
          graph_model: String(this.roadSyntaxGraphModel || 'segment'),
          main_tab: String(this.roadSyntaxMainTab || 'params'),
          metric: String(this.roadSyntaxMetric || 'connectivity'),
          radius_label: String(this.roadSyntaxRadiusLabel || 'global'),
          color_scale: String(this.roadSyntaxDepthmapColorScale || 'axmanesque'),
          display_blue: Number(this.roadSyntaxDisplayBlue) || 0,
          display_red: Number(this.roadSyntaxDisplayRed) || 1,
          panel_active: this.activeStep3Panel === 'syntax',
        },
      }
    },
    saveAnalysisHistoryAsync(polygon, selectedCats, pois, options = {}) {
      if (!this.selectedPoint) return
      const currentHistoryId = String(this.currentHistoryRecordId || '').trim()
      const selectedCatsSafe = Array.isArray(selectedCats)
        ? selectedCats
        : (typeof this.buildSelectedCategoryBuckets === 'function' ? this.buildSelectedCategoryBuckets() : [])
      const typesLabel = selectedCatsSafe.map((c) => c.name).join(',')
      const drawnPolygonForSave = (
        this.isochroneScopeMode === 'area'
        && Array.isArray(this.drawnScopePolygon)
        && this.drawnScopePolygon.length >= 3
      )
        ? this._closePolygonRing(this.normalizePath(this.drawnScopePolygon, 3, 'history.drawn_polygon'))
        : null
      const poiList = Array.isArray(pois)
        ? pois
        : (Array.isArray(this.allPoisDetails) ? this.allPoisDetails : [])
      const compactPois = poiList.map((p) => ({
        id: p && p.id ? String(p.id) : '',
        name: p && p.name ? String(p.name) : 'unknown',
        location: Array.isArray(p && p.location) ? [p.location[0], p.location[1]] : null,
        address: p && p.address ? String(p.address) : '',
        type: p && p.type ? String(p.type) : '',
        adname: p && p.adname ? String(p.adname) : '',
        year: Number.isFinite(Number(p && p.year)) ? Number(p.year) : null,
        lines: Array.isArray(p && p.lines) ? p.lines : [],
      })).filter((p) => Array.isArray(p.location) && p.location.length === 2)
      const rawPoiResultsByYear = Array.isArray(options && options.poiResultsByYear)
        ? options.poiResultsByYear
        : []
      const poiResultsByYear = rawPoiResultsByYear.map((item) => {
        const source = this.normalizePoiSource(item && item.source, 'local')
        const year = Number.isFinite(Number(item && item.year)) ? Number(item.year) : null
        const poisForYear = Array.isArray(item && item.pois) ? item.pois : []
        const compactYearPois = poisForYear.map((p) => ({
          id: p && p.id ? String(p.id) : '',
          name: p && p.name ? String(p.name) : 'unknown',
          location: Array.isArray(p && p.location) ? [p.location[0], p.location[1]] : null,
          address: p && p.address ? String(p.address) : '',
          type: p && p.type ? String(p.type) : '',
          adname: p && p.adname ? String(p.adname) : '',
          year: Number.isFinite(Number(p && p.year)) ? Number(p.year) : year,
          lines: Array.isArray(p && p.lines) ? p.lines : [],
        })).filter((p) => Array.isArray(p.location) && p.location.length === 2)
        return {
          source,
          year,
          pois: compactYearPois,
        }
      }).filter((item) => item.year !== null && item.pois.length)
      const resolvedPolygon = Array.isArray(polygon) && polygon.length
        ? polygon
        : this.getIsochronePolygonPayload()
      const preservedHistoryPolygonWgs84 = (
        currentHistoryId
        && Array.isArray(this.currentHistoryPolygonWgs84)
        && this.currentHistoryPolygonWgs84.length
      )
        ? JSON.parse(JSON.stringify(this.currentHistoryPolygonWgs84))
        : null
      const selectedYear = Number.isFinite(Number(options && options.selectedYear))
        ? Number(options.selectedYear)
        : (Number.isFinite(Number(this.resultPoiYear || this.poiYearSource))
          ? Number(this.resultPoiYear || this.poiYearSource)
          : null)
      const requestedYears = Array.isArray(options && options.years)
        ? options.years.map((item) => Number(item)).filter((item) => Number.isFinite(item))
        : []
      const yearsForSave = Array.from(new Set([
        ...(Array.isArray(this.currentHistoryAvailablePoiYears) ? this.currentHistoryAvailablePoiYears : []),
        ...requestedYears,
        ...(selectedYear !== null ? [selectedYear] : []),
      ].map((item) => Number(item)).filter((item) => Number.isFinite(item)))).sort((a, b) => a - b)
      if (
        String(this.scopeSource || '').trim().toLowerCase() === 'history'
        && currentHistoryId
        && !poiResultsByYear.length
        && (
          selectedYear === null
          || Number(this.currentHistorySelectedPoiYear) === selectedYear
          || (
            Array.isArray(this.currentHistoryAvailablePoiYears)
            && (
              this.currentHistoryAvailablePoiYears.length === 0
              || this.currentHistoryAvailablePoiYears.map((item) => Number(item)).includes(selectedYear)
            )
          )
        )
      ) {
        this.poiStatus = '当前历史年份已保存，无需重复保存'
        return
      }
      const payload = {
        history_id: currentHistoryId || null,
        center: [this.selectedPoint.lng, this.selectedPoint.lat],
        polygon: resolvedPolygon,
        polygon_wgs84: preservedHistoryPolygonWgs84,
        drawn_polygon: Array.isArray(drawnPolygonForSave) && drawnPolygonForSave.length >= 4
          ? drawnPolygonForSave
          : null,
        pois: compactPois,
        keywords: typesLabel,
        location_name: this.selectedPoint.lng.toFixed(4) + ',' + this.selectedPoint.lat.toFixed(4),
        mode: this.transportMode,
        time_min: parseInt(this.timeHorizon),
        source: this.normalizePoiSource(this.resultDataSource || this.poiDataSource, 'local'),
        year: selectedYear,
        years: yearsForSave.length ? yearsForSave : (selectedYear !== null ? [selectedYear] : []),
        poi_results_by_year: poiResultsByYear.length
          ? poiResultsByYear
          : [{
            source: this.normalizePoiSource(this.resultDataSource || this.poiDataSource, 'local'),
            year: selectedYear,
            pois: compactPois,
          }],
      }
      const savePromise = fetch('/api/v1/analysis/history/save', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        })
          .then(async (res) => {
            if (!res.ok) {
              let detail = ''
              try {
                detail = (await res.text()) || ''
              } catch (_) {}
              throw new Error(`HTTP ${res.status}${detail ? `: ${detail.slice(0, 200)}` : ''}`)
            }
            return res.json().catch(() => ({}))
          })
          .then((data) => {
            const historyId = String((data && data.history_id) || '').trim()
            if (historyId) {
              this.currentHistoryRecordId = historyId
              if (selectedYear !== null || yearsForSave.length) {
                const yearSet = new Set(
                  (Array.isArray(this.currentHistoryAvailablePoiYears) ? this.currentHistoryAvailablePoiYears : [])
                    .map((item) => Number(item))
                    .filter((item) => Number.isFinite(item))
                )
                yearsForSave.forEach((item) => yearSet.add(item))
                if (selectedYear !== null) yearSet.add(selectedYear)
                this.currentHistoryAvailablePoiYears = Array.from(yearSet).sort((a, b) => a - b)
                if (selectedYear !== null) this.currentHistorySelectedPoiYear = selectedYear
              }
              if (Array.isArray(payload.polygon_wgs84) && payload.polygon_wgs84.length) {
                this.currentHistoryPolygonWgs84 = JSON.parse(JSON.stringify(payload.polygon_wgs84))
              }
              if (this.lastIsochroneGeoJSON) {
                this.scopeSource = 'history'
              }
            }
            if (typeof this.loadHistoryList === 'function') {
              this.loadHistoryList({
                force: true,
                keepExisting: true,
                background: true,
                hardRefresh: true,
              }).catch((err) => {
                console.warn('refresh history list after save failed', err)
              })
            }
            if (historyId && typeof this.persistAnalysisArtifactQuietly === 'function') {
              this.persistAnalysisArtifactQuietly('scope')
            }
            return data
          })
          .catch((err) => {
            console.warn('Failed to save history', err)
            const message = err && err.message ? err.message : String(err)
              this.poiStatus = `分析完成，但历史保存失败：${message}`
          throw err
          })
      return savePromise
    },
    cloneArtifactValue(value) {
      if (value === undefined || value === null) return Array.isArray(value) ? [] : {}
      try {
        return JSON.parse(JSON.stringify(value))
      } catch (_) {
        return Array.isArray(value) ? value.slice() : Object.assign({}, value)
      }
    },
    normalizeArtifactParams(params = {}) {
      return this.cloneArtifactValue(params && typeof params === 'object' ? params : {})
    },
    buildAnalysisScopeFingerprint() {
      const scope = typeof this.getIsochronePolygonPayload === 'function' ? this.getIsochronePolygonPayload() : []
      const payload = {
        polygon: scope,
        mode: String(this.transportMode || ''),
        time_min: Number(this.timeHorizon || 0) || 0,
        center: this.selectedPoint ? [Number(this.selectedPoint.lng), Number(this.selectedPoint.lat)] : [],
      }
      try {
        return JSON.stringify(payload)
      } catch (_) {
        return `${payload.mode}:${payload.time_min}:${scope.length}`
      }
    },
    buildCurrentScopeArtifactPayload() {
      const polygon = typeof this.getIsochronePolygonPayload === 'function' ? this.getIsochronePolygonPayload() : []
      const drawnPolygon = Array.isArray(this.drawnScopePolygon) ? this.drawnScopePolygon : []
      return {
        params: {
          mode: String(this.transportMode || ''),
          time_min: Number(this.timeHorizon || 0) || 0,
          center: this.selectedPoint ? [Number(this.selectedPoint.lng), Number(this.selectedPoint.lat)] : [],
          scope_source: String(this.scopeSource || ''),
        },
        payload: {
          polygon,
          drawn_polygon: drawnPolygon,
          center: this.selectedPoint ? [Number(this.selectedPoint.lng), Number(this.selectedPoint.lat)] : [],
          mode: String(this.transportMode || ''),
          time_min: Number(this.timeHorizon || 0) || 0,
          area: null,
        },
        summary: {
          has_polygon: Array.isArray(polygon) && polygon.length > 0,
          mode: String(this.transportMode || ''),
          time_min: Number(this.timeHorizon || 0) || 0,
        },
      }
    },
    buildAnalysisArtifactBundle(artifactType = '') {
      const type = String(artifactType || '').trim()
      if (type === 'scope') return this.buildCurrentScopeArtifactPayload()
      if (type === 'poi_raster_grid') {
        const params = {
          grid_type: 'shared_raster',
          cell_id_source: 'population_nightlight_shared_cell_id',
          source: this.normalizePoiSource ? this.normalizePoiSource(this.resultDataSource || this.poiDataSource, 'local') : String(this.resultDataSource || this.poiDataSource || ''),
          year: Number(this.getPoiRasterGridYear ? this.getPoiRasterGridYear() : (this.poiYearSource || this.resultPoiYear)) || null,
          neighbor_ring: Number(this.h3NeighborRing || 0) || 1,
        }
        const features = Array.isArray(this.poiGridFeatures) ? this.poiGridFeatures : []
        return {
          params,
          payload: {
            grid: {
              type: 'FeatureCollection',
              grid_type: 'shared_raster',
              cell_id_source: 'population_nightlight_shared_cell_id',
              scope_id: (this.poiGridSummary && this.poiGridSummary.scope_id) || null,
              features,
              count: features.length,
              cell_count: features.length,
            },
            summary: this.cloneArtifactValue(this.poiGridSummary || {}),
            charts: this.cloneArtifactValue(this.h3AnalysisCharts || {}),
            ...params,
          },
          summary: this.cloneArtifactValue(this.poiGridSummary || {}),
        }
      }
      if (type === 'poi_h3_grid') {
        const features = Array.isArray(this.h3AnalysisGridFeatures) ? this.h3AnalysisGridFeatures : []
        const params = {
          resolution: Number(this.h3GridResolution || 0) || 10,
          neighbor_ring: Number(this.h3NeighborRing || 0) || 1,
          include_mode: String(this.h3GridIncludeMode || 'intersects'),
          min_overlap_ratio: String(this.h3GridIncludeMode || '') === 'intersects' ? Number(this.h3GridMinOverlapRatio || 0) || 0 : 0,
          source: this.normalizePoiSource ? this.normalizePoiSource(this.resultDataSource || this.poiDataSource, 'local') : String(this.resultDataSource || this.poiDataSource || ''),
          year: Number(this.poiYearSource || this.resultPoiYear || 0) || null,
        }
        return {
          params,
          payload: {
            year: params.year,
            params: this.cloneArtifactValue(params),
            grid: {
              type: 'FeatureCollection',
              features,
              count: Number(this.h3GridCount || features.length || 0) || 0,
              resolution: params.resolution,
              include_mode: params.include_mode,
              min_overlap_ratio: params.min_overlap_ratio,
            },
            summary: this.cloneArtifactValue(this.h3AnalysisSummary || {}),
            charts: this.cloneArtifactValue(this.h3AnalysisCharts || {}),
          },
          summary: this.cloneArtifactValue(this.h3AnalysisSummary || {}),
        }
      }
      if (type === 'population') {
        const params = {
          year: String(typeof this.getPopulationSelectedYear === 'function' ? this.getPopulationSelectedYear() : (this.populationSelectedYear || '')),
          view: String(this.populationAnalysisView || 'density'),
        }
        const layer = this.populationLayer && typeof this.populationLayer === 'object' ? this.populationLayer : {}
        return {
          params,
          payload: {
            overview: this.cloneArtifactValue(this.populationOverview || {}),
            summary: this.cloneArtifactValue((this.populationOverview && this.populationOverview.summary) || {}),
            grid_evidence: typeof this.buildAgentPopulationGridEvidence === 'function' ? this.buildAgentPopulationGridEvidence() : {},
            layer: this.cloneArtifactValue(layer),
            year: params.year,
            view: params.view,
          },
          summary: this.cloneArtifactValue((this.populationOverview && this.populationOverview.summary) || {}),
        }
      }
      if (type === 'nightlight') {
        const params = {
          year: Number(this.nightlightSelectedYear || 0) || null,
          view: String(this.nightlightAnalysisView || 'radiance'),
        }
        const layer = this.nightlightLayer && typeof this.nightlightLayer === 'object' ? this.nightlightLayer : {}
        return {
          params,
          payload: {
            overview: this.cloneArtifactValue(this.nightlightOverview || {}),
            summary: this.cloneArtifactValue((this.nightlightOverview && this.nightlightOverview.summary) || {}),
            layer: this.cloneArtifactValue(layer),
            raster: this.cloneArtifactValue(this.nightlightRaster || {}),
            year: params.year,
            view: params.view,
          },
          summary: this.cloneArtifactValue((this.nightlightOverview && this.nightlightOverview.summary) || {}),
        }
      }
      if (type === 'road_syntax') {
        const params = {
          graph_model: String(this.roadSyntaxGraphModel || 'segment'),
          mode: String(this.transportMode || 'walking'),
          metric: String(this.roadSyntaxLastMetricTab || this.roadSyntaxMetric || ''),
        }
        const roadFeatures = Array.isArray(this.roadSyntaxRoadFeatures) ? this.roadSyntaxRoadFeatures : []
        const nodeFeatures = Array.isArray(this.roadSyntaxNodes) ? this.roadSyntaxNodes : []
        return {
          params,
          payload: {
            summary: this.cloneArtifactValue(this.roadSyntaxSummary || {}),
            diagnostics: this.cloneArtifactValue(this.roadSyntaxDiagnostics || {}),
            roads: { type: 'FeatureCollection', features: roadFeatures, count: roadFeatures.length },
            nodes: { type: 'FeatureCollection', features: nodeFeatures, count: nodeFeatures.length },
            webgl: this.cloneArtifactValue(this.roadSyntaxWebglPayload || {}),
            graph_model: params.graph_model,
            mode: params.mode,
            metric: params.metric,
          },
          summary: this.cloneArtifactValue(this.roadSyntaxSummary || {}),
        }
      }
      return null
    },
    async ensureCurrentHistoryRecordForArtifact() {
      const currentHistoryId = String(this.currentHistoryRecordId || '').trim()
      if (currentHistoryId) return currentHistoryId
      if (typeof this.saveAnalysisHistoryAsync !== 'function') return ''
      const result = await this.saveAnalysisHistoryAsync(
        typeof this.getIsochronePolygonPayload === 'function' ? this.getIsochronePolygonPayload() : [],
        typeof this.buildSelectedCategoryBuckets === 'function' ? this.buildSelectedCategoryBuckets() : [],
        Array.isArray(this.allPoisDetails) ? this.allPoisDetails : []
      ).catch(() => null)
      return String((result && result.history_id) || this.currentHistoryRecordId || '').trim()
    },
    async persistAnalysisArtifact(artifactType = '') {
      const type = String(artifactType || '').trim()
      if (!type) return null
      const historyId = await this.ensureCurrentHistoryRecordForArtifact()
      if (!historyId) return null
      const bundle = this.buildAnalysisArtifactBundle(type)
      if (!bundle) return null
      const res = await fetch(`/api/v1/analysis/history/${encodeURIComponent(historyId)}/artifacts`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          artifact_type: type,
          params: this.normalizeArtifactParams(bundle.params),
          payload: this.cloneArtifactValue(bundle.payload || {}),
          summary: this.cloneArtifactValue(bundle.summary || {}),
          scope_fingerprint: this.buildAnalysisScopeFingerprint(),
          data_version: 'v1',
        }),
      })
      if (!res.ok) {
        let detail = ''
        try { detail = await res.text() } catch (_) {}
        throw new Error(detail || `artifact ${type} 保存失败`)
      }
      return res.json()
    },
    persistAnalysisArtifactQuietly(artifactType = '') {
      this.persistAnalysisArtifact(artifactType).catch((err) => {
        console.warn('[analysis-artifact] save failed', artifactType, err)
      })
    },
  }
}

export { createAnalysisHistoryOrchestratorMethods }
