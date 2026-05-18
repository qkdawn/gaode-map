function createAnalysisPoiFlowOrchestratorMethods() {
  return {
    parsePoiSseChunk(rawChunk) {
      const lines = String(rawChunk || '').split(/\r?\n/)
      let type = 'message'
      const dataLines = []
      lines.forEach((line) => {
        if (line.startsWith('event:')) {
          type = line.slice(6).trim() || 'message'
        } else if (line.startsWith('data:')) {
          dataLines.push(line.slice(5).trimStart())
        }
      })
      const rawData = dataLines.join('\n').trim()
      const payload = rawData ? JSON.parse(rawData) : {}
      return { type, payload }
    },

    async consumePoiSseStream(response, onEvent) {
      if (!response || !response.body || typeof response.body.getReader !== 'function') {
        throw new Error('POI 流式响应缺少可读数据流')
      }
      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      while (true) {
        const { value, done } = await reader.read()
        buffer += decoder.decode(value || new Uint8Array(), { stream: !done })
        let splitIndex = buffer.indexOf('\n\n')
        while (splitIndex >= 0) {
          const rawChunk = buffer.slice(0, splitIndex)
          buffer = buffer.slice(splitIndex + 2)
          if (rawChunk.trim()) onEvent(this.parsePoiSseChunk(rawChunk))
          splitIndex = buffer.indexOf('\n\n')
        }
        if (done) break
      }
      if (buffer.trim()) onEvent(this.parsePoiSseChunk(buffer))
    },

    applyPoiFetchProgressEvent(event) {
      const payload = event && event.payload && typeof event.payload === 'object' ? event.payload : {}
      const type = String((event && event.type) || payload.type || '').trim()
      const progress = Number(payload.progress)
      if (Number.isFinite(progress)) {
        this.fetchProgress = Math.max(0, Math.min(100, Math.round(progress)))
      }
      if (type === 'start') {
        const years = Array.isArray(payload.years) ? payload.years.join(' / ') : ''
        this.poiStatus = years ? `Fetching ${years} POI years...` : 'Fetching POI years...'
        if (!Number(this.fetchProgress || 0)) this.fetchProgress = 1
        return
      }
      if (type === 'category_start') {
        const label = this.getPoiSourceLabel(payload.source, payload.year)
        const category = String(payload.category || '未命名分类')
        const index = Number(payload.category_index || 0)
        const count = Number(payload.category_count || 0)
        const completed = Number(payload.completed_units || 0)
        const total = Number(payload.total_units || 0)
        if (total > 0) {
          const unitProgress = Math.floor((completed / total) * 100)
          this.fetchProgress = Math.max(Number(this.fetchProgress || 0), Math.max(1, unitProgress))
        }
        this.poiStatus = `Fetching ${label}: ${index || '-'} / ${count || '-'} categories · ${category}`
        this.fetchSubtypeProgress = Object.assign({}, this.fetchSubtypeProgress || {}, {
          categoryName: category,
        })
        return
      }
      if (type === 'category_complete') {
        const label = this.getPoiSourceLabel(payload.source, payload.year)
        const category = String(payload.category || '未命名分类')
        const completed = Number(payload.completed_units || 0)
        const total = Number(payload.total_units || 0)
        const count = Number(payload.count || 0)
        const suffix = payload.status === 'failed' ? '失败' : `${count} POIs`
        this.poiStatus = `Fetched ${label}: ${completed || '-'} / ${total || '-'} units · ${category} ${suffix}`
        return
      }
      if (type === 'category_progress') {
        const label = this.getPoiSourceLabel(payload.source, payload.year)
        const category = String(payload.category || '未命名分类')
        const requestCount = Number(payload.request_count || 0)
        const apiCallCount = Number(payload.api_call_count || 0)
        const tileCount = Number(payload.tile_count || 0)
        const saturated = Number(payload.saturated_queries || 0)
        const expanded = Number(payload.expanded_type_queries || 0)
        const suffix = [
          requestCount > 0 ? `${requestCount} requests` : '',
          apiCallCount > 0 ? `${apiCallCount} api` : '',
          tileCount > 0 ? `${tileCount} tiles` : '',
          saturated > 0 ? `${saturated} saturated` : '',
          expanded > 0 ? `${expanded} subtype` : '',
        ].filter(Boolean).join(' · ')
        this.poiStatus = `Fetching ${label}: ${category}${suffix ? ` · ${suffix}` : ''}`
        this.fetchSubtypeProgress = Object.assign({}, this.fetchSubtypeProgress || {}, {
          categoryName: category,
        })
        return
      }
      if (type === 'year_complete') {
        const label = this.getPoiSourceLabel(payload.source, payload.year)
        this.poiStatus = `Fetched ${label}: ${Number(payload.count || 0)} POIs`
      }
    },

    async fetchPoiMultiYearStream(payload) {
      const res = await fetch('/api/v1/analysis/pois/multi-year/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        signal: this.abortController.signal,
      })
      if (!res.ok) {
        let detail = ''
        try { detail = await res.text() } catch (_) { }
        throw new Error(detail || `HTTP ${res.status}`)
      }
      let finalResult = null
      await this.consumePoiSseStream(res, (event) => {
        this.applyPoiFetchProgressEvent(event)
        const payload = event && event.payload ? event.payload : {}
        if ((event && event.type) === 'final' || payload.type === 'final') {
          finalResult = payload.result || null
        }
        if ((event && event.type) === 'error') {
          throw new Error(payload.message || 'POI 流式抓取失败')
        }
      })
      if (!finalResult) throw new Error('POI fetch stream returned no final payload')
      return finalResult
    },

    async fetchPoisForYear(polygon, selectedCats, poiSelection, options = {}) {
      const batchSize = Number(options.batchSize) || 4
      const yearIndex = Number(options.yearIndex || 0)
      const yearCount = Number(options.yearCount || 1)
      const totalCats = selectedCats.length
      const fetchErrors = []
      const sourceLabel = this.getPoiSourceLabel(poiSelection.source, poiSelection.year)
      const pois = []
      if (selectedCats[0]) {
        this.updateFetchSubtypeProgressDisplay(selectedCats[0])
      }

      const fetchOneCategory = async (cat) => {
        const payload = {
          polygon,
          keywords: '',
          types: String(cat.types || ''),
          source: poiSelection.source,
          year: poiSelection.year,
          save_history: false,
          center: [this.selectedPoint.lng, this.selectedPoint.lat],
          time_min: parseInt(this.timeHorizon),
          mode: this.transportMode,
          location_name: this.selectedPoint.name || (this.selectedPoint.lng.toFixed(4) + ',' + this.selectedPoint.lat.toFixed(4)),
        }

        try {
          const res = await fetch('/api/v1/analysis/pois', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
            signal: this.abortController.signal,
          })
          if (!res.ok) {
            let detail = ''
            try {
              detail = await res.text()
            } catch (_) { }
            return {
              list: [],
              error: `HTTP ${res.status}${detail ? ` ${detail.slice(0, 240)}` : ''}`,
            }
          }
          const data = await res.json()
          return { list: data.pois || [], error: '' }
        } catch (err) {
          if (err.name !== 'AbortError') {
            console.warn(`Failed to fetch category ${cat.name}`, err)
          }
          return {
            list: [],
            error: err && err.message ? String(err.message) : String(err),
          }
        }
      }

      for (let i = 0; i < selectedCats.length; i += batchSize) {
        if (this.abortController.signal.aborted) return { pois, errors: fetchErrors, aborted: true }
        const batch = selectedCats.slice(i, i + batchSize)
        const resultsArray = await Promise.all(batch.map(fetchOneCategory))
        resultsArray.forEach((result, index) => {
          const list = Array.isArray(result && result.list) ? result.list : []
          if (list && list.length) pois.push(...list)
          const cat = batch[index]
          if (cat && result && result.error) {
            fetchErrors.push({
              year: poiSelection.year,
              category: cat.name || cat.id || `cat_${i + index + 1}`,
              error: result.error,
            })
          }
          if (cat) {
            this.accumulateFetchSubtypeHits(cat, list || [])
          }
        })

        const done = Math.min(i + batch.length, totalCats)
        const completedUnits = yearIndex * totalCats + done
        const totalUnits = Math.max(1, yearCount * totalCats)
        this.fetchProgress = Math.round((completedUnits / totalUnits) * 100)
        this.poiStatus = `Fetching ${sourceLabel}: ${done}/${totalCats} categories, ${pois.length} POIs`
      }

      return {
        pois: this.deduplicateFetchedPois(pois),
        errors: fetchErrors,
        aborted: false,
      }
    },

    async fetchPois(options = {}) {
      if (!this.lastIsochroneGeoJSON) return
      const preserveCurrentPanel = !!(options && options.preserveCurrentPanel)
      this.isFetchingPois = true
      this.fetchProgress = 0
      this.poiStatus = 'Preparing POI fetch...'
      this.resetRoadSyntaxState()
      this.resetFetchSubtypeProgress()

      this.clearPoiOverlayLayers({
        reason: 'fetch_pois_start',
        clearManager: true,
        clearSimpleMarkers: true,
        resetFilterPanel: true,
      })
      this.allPoisDetails = []
      this.poiCategorySummary = []
      this.poiFetchErrors = []

      try {
        const polygon = this.getIsochronePolygonPayload()
        const selectedCats = this.buildSelectedCategoryBuckets()
        if (selectedCats.length === 0) {
          alert('Please select at least one POI category')
          this.isFetchingPois = false
          return
        }

        const selectedYears = this.getSelectedPoiYears()
        this.abortController = new AbortController()
        this.poiStatus = `Fetching ${selectedYears.join(' / ')} POI years...`
        const payload = {
          polygon,
          categories: selectedCats.map((cat) => ({
            id: String(cat.id || ''),
            name: String(cat.name || cat.id || ''),
            types: String(cat.types || ''),
          })).filter((cat) => cat.id && cat.types),
          years: selectedYears,
          save_history: true,
          history_id: String(this.currentHistoryRecordId || '').trim() || null,
          center: [this.selectedPoint.lng, this.selectedPoint.lat],
          time_min: parseInt(this.timeHorizon),
          mode: this.transportMode,
          location_name: this.selectedPoint.name || (this.selectedPoint.lng.toFixed(4) + ',' + this.selectedPoint.lat.toFixed(4)),
        }

        if (this.abortController.signal.aborted) return
        const data = await this.fetchPoiMultiYearStream(payload)
        const yearlyResults = Array.isArray(data && data.results_by_year) ? data.results_by_year : []
        if (!yearlyResults.length) {
          throw new Error('POI fetch returned no usable data')
        }

        const successfulYears = (Array.isArray(data.years) && data.years.length ? data.years : yearlyResults.map((item) => item.year))
          .map((item) => Number(item))
          .filter((item) => Number.isFinite(item))
          .sort((a, b) => a - b)
        const selectedYearRaw = Number(data.selected_year)
        const selectedYear = Number.isFinite(selectedYearRaw)
          ? selectedYearRaw
          : (successfulYears.length ? successfulYears[successfulYears.length - 1] : null)
        const displayResult = yearlyResults.find((item) => Number(item.year) === Number(selectedYear)) || yearlyResults[yearlyResults.length - 1]
        const displaySelection = this.resolvePoiYearSourceSelection(displayResult.year)
        this.allPoisDetails = this.deduplicateFetchedPois(Array.isArray(data.display_pois) ? data.display_pois : displayResult.pois)
        this.poiCategorySummary = Array.isArray(data.category_summary) ? data.category_summary : []
        this.poiResultsByYear = yearlyResults
        this.fetchProgress = 100
        this.poiDataSource = displaySelection.source
        this.resultDataSource = displaySelection.source
        this.resultPoiYear = displaySelection.year
        this.poiYearSource = String(displaySelection.year)
        this.currentHistorySelectedPoiYear = displaySelection.year
        this.currentHistoryAvailablePoiYears = successfulYears
        const historyId = String((data && data.history_id) || '').trim()
        if (historyId) {
          this.currentHistoryRecordId = historyId
          this.scopeSource = 'history'
        }
        this.poiStatus = ''
        const fetchErrors = Array.isArray(data.errors) ? data.errors : []
        this.poiFetchErrors = fetchErrors
        if (fetchErrors.length > 0) {
          console.warn('[poi-fetch] partial category failures', fetchErrors)
          this.poiStatus = `POI 部分分类抓取失败：${fetchErrors.length} 条，详见抓取面板`
        }

        this.rebuildPoiRuntimeSystem(this.allPoisDetails)

        if (preserveCurrentPanel) {
          this.updatePoiCharts()
          this.resizePoiChart()
        } else {
          setTimeout(() => {
            this.activeStep3Panel = 'poi'
            this.lastNonAgentStep3Panel = 'poi'
            if (typeof this.resetAnalysisDisplayTargetsForPanel === 'function') {
              this.resetAnalysisDisplayTargetsForPanel('poi', { apply: false })
            }
            this.applySimplifyConfig()
            this.updatePoiCharts()
            this.resizePoiChart()
          }, 120)
        }
      } catch (e) {
        if (e.name !== 'AbortError') {
          console.error(e)
          this.poiStatus = `Failed: ${e.message}`
        }
      } finally {
        this.isFetchingPois = false
        this.abortController = null
        this.resetFetchSubtypeProgress()
      }
    },

    resolvePoiYearSourceSelection(value) {
      const year = Number(value || 2020)
      if (year === 2026) {
        return { source: 'gaode', year: 2026 }
      }
      if (year === 2022 || year === 2024) {
        return { source: 'local', year }
      }
      return { source: 'local', year: 2020 }
    },

    async onPoiYearSourceChange() {
      const nextYear = String(this.poiYearSource || '').trim()
      const scopeSource = String(this.scopeSource || '').trim().toLowerCase()
      if (scopeSource === 'history' && String(this.currentHistoryRecordId || '').trim()) {
        await this.loadCurrentHistoryPoiYear(nextYear)
        return
      }
      const poiSelection = this.resolvePoiYearSourceSelection(nextYear)
      this.resultDataSource = poiSelection.source
      this.poiDataSource = poiSelection.source
      this.resultPoiYear = poiSelection.year
    },

    computePoiStats(points) {
      const labels = this.poiCategories.map((c) => c.name)
      const colors = this.poiCategories.map((c) => c.color || '#888')
      const values = this.poiCategories.map(() => 0)
      const shouldUseBackendSummary = points === this.allPoisDetails
        && Array.isArray(this.poiCategorySummary)
        && this.poiCategorySummary.length > 0
      if (shouldUseBackendSummary) {
        const countById = {}
        this.poiCategorySummary.forEach((item) => {
          if (!item) return
          countById[String(item.id || '')] = Number(item.count) || 0
        })
        this.poiCategories.forEach((cat, idx) => {
          values[idx] = countById[String(cat.id || '')] || 0
        })
        return { labels, colors, values }
      }

      const indexMap = {}
      this.poiCategories.forEach((c, idx) => {
        indexMap[c.id] = idx
      })
      ;(points || []).forEach((p) => {
        const cid = this.resolvePoiCategoryId(p && p.type)
        if (!cid) return
        const idx = indexMap[cid]
        if (Number.isInteger(idx) && idx >= 0) values[idx] += 1
      })
      return { labels, colors, values }
    },

    getPoiCategoryChartStats() {
      const source = Array.isArray(this.allPoisDetails) && this.allPoisDetails.length
        ? this.allPoisDetails
        : ((this.markerManager && typeof this.markerManager.getVisiblePoints === 'function')
            ? this.markerManager.getVisiblePoints()
            : [])
      return this.computePoiStats(source)
    },

    updatePoiCharts() {
      if (!Array.isArray(this.allPoisDetails) || !this.allPoisDetails.length) return
      if (this.activeStep3Panel === 'poi' && this.poiSubTab !== 'category') {
        this.refreshPoiKdeOverlay()
        return
      }

      const el = document.getElementById('poiChart')
      if (!el || !window.echarts) return

      const existingChart = echarts.getInstanceByDom(el)
      if (existingChart && el.clientWidth > 0) {
        this.poiChart = existingChart
        const stats = this.getPoiCategoryChartStats()
        const safeValues = stats.values.map((v) => (Number.isFinite(v) ? v : 0))

        const option = {
          yAxis: {
            type: 'category',
            inverse: true,
            data: stats.labels,
          },
          series: [{
            data: safeValues,
            itemStyle: {
              color: (params) => stats.colors[params.dataIndex] || '#888',
            },
          }],
        }
        existingChart.setOption(option, false)
        this.refreshPoiKdeOverlay()
        return
      }

      setTimeout(() => {
        const chart = this.initPoiChart()
        if (!chart) return

        const stats = this.getPoiCategoryChartStats()
        const safeValues = stats.values.map((v) => (Number.isFinite(v) ? v : 0))

        const option = {
          grid: { left: 50, right: 20, top: 10, bottom: 10, containLabel: true },
          xAxis: {
            type: 'value',
            axisLine: { show: false },
            axisTick: { show: false },
            splitLine: { lineStyle: { color: '#eee' } },
          },
          yAxis: {
            type: 'category',
            inverse: true,
            data: stats.labels,
            axisLine: { show: false },
            axisTick: { show: false },
          },
          series: [{
            type: 'bar',
            data: safeValues,
            barWidth: 12,
            itemStyle: {
              color: (params) => stats.colors[params.dataIndex] || '#888',
            },
          }],
        }
        try {
          chart.setOption(option, true)
          chart.resize()
        } catch (err) {
          console.error('ECharts setOption error:', err)
        }
        this.refreshPoiKdeOverlay()
      }, 100)
    },
  }
}

export { createAnalysisPoiFlowOrchestratorMethods }
