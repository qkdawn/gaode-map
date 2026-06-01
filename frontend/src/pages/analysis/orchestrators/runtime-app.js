import { createApp, markRaw } from 'vue'
import { createAnalysisAgentInitialState, createAnalysisAgentSessionMethods } from '../../../features/agent/sessions'
import { createAnalysisBootstrapContext } from './bootstrap-context'
import { mountAnalysisRuntimeApp } from '../views/runtime-mount'
import { createAnalysisLifecycleHooks } from './lifecycle'

// Bootstrap runtime entry for the modular analysis app.
export function runAnalysisBootstrapApp() {
          const injectedTypeMapConfig = (window.__ANALYSIS_BOOTSTRAP__ && window.__ANALYSIS_BOOTSTRAP__.typeMapConfig) || { groups: [] };
          const context = createAnalysisBootstrapContext({
              typeMapConfig: injectedTypeMapConfig,
          });
          const {
              pinia,
              initialState,
              storeBackedComputed,
              roadSyntaxModulesReady,
              roadSyntaxModuleMissing,
              methods,
          } = context;
          const {
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
          } = methods;
          const lifecycleHooks = createAnalysisLifecycleHooks({
              roadSyntaxModulesReady,
              roadSyntaxModuleMissing,
          });
          const agentSessionMethods = createAnalysisAgentSessionMethods()

          const analysisApp = createApp({
              data() {
                  return {
                      loadingConfig: true,
                      config: null,

                      ...initialState,
                      ...createAnalysisAgentInitialState(),
  
                      // Instances
                      placeSearch: null,
                      placeSearchErrorListener: null,
                      placeSearchLoadingPromise: null,
                      placeSearchBuildToken: 0,
                      drawScopeMouseTool: null,
                      drawScopeDrawHandler: null,
                      drawScopeActive: false,
                      amapRuntimeErrorListener: null,
                      amapRuntimeRejectionListener: null,
                  }
              },
              computed: storeBackedComputed,
              mounted: lifecycleHooks.mounted,
              beforeUnmount: lifecycleHooks.beforeUnmount,
              watch: lifecycleHooks.watch,
              methods: {
                  ...analysisWorkbenchMethods,
                  ...analysisWorkbenchSessionMethods,
                  ...isochroneMethods,
                  ...poiPanelMethods,
                  ...poiRuntimeMethods,
                  ...historyListMethods,
                  ...historyMethods,
                  ...h3Methods,
                  ...populationMethods,
                  ...nightlightMethods,
                  ...gwrMethods,
                  ...timeseriesMethods,
                  ...exportMethods,
                  ...poiMapVisibilityAdapterMethods,
                  ...mapOrchestratorMethods,
                  ...historyOrchestratorMethods,
                  ...exportOrchestratorMethods,
                  ...poiFlowOrchestratorMethods,
                  ...roadSyntaxOverlayCommitMethods,
                  ...roadSyntaxControllerCoreMethods,
                  ...roadSyntaxWebglMethods,
                  ...roadSyntaxUiMethods,
                  ...agentSessionMethods,
                  openAgentPanel() {
                      this.agentWorkspaceView = 'report';
                      if (typeof this.selectStep3Panel === 'function') {
                          this.selectStep3Panel('agent');
                          return;
                      }
                      this.activeStep3Panel = 'agent';
                      this.ensureAgentPanelReady();
                  },
                  getAgentReturnPanel() {
                      const candidate = String(this.lastNonAgentStep3Panel || '').trim();
                      if (candidate && candidate !== 'agent' && typeof this.isStep3PanelVisible === 'function' && this.isStep3PanelVisible(candidate)) {
                          return candidate;
                      }
                      return 'poi';
                  },
                  exitAgentPanel() {
                      const targetPanel = this.getAgentReturnPanel();
                      if (typeof this.selectStep3Panel === 'function') {
                          this.selectStep3Panel(targetPanel);
                          return;
                      }
                      this.activeStep3Panel = targetPanel;
                  },
                  isAgentWorkspaceActive() {
                      return this.sidebarView === 'wizard'
                          && Number(this.step) === 2
                          && this.activeStep3Panel === 'agent';
                  },
                  resetAgentPanelState() {
                      if (typeof this.destroyAllAgentRuns === 'function') {
                          this.destroyAllAgentRuns();
                      }
                      if (typeof this.stopAllSummaryTaskLogTracking === 'function') {
                          this.stopAllSummaryTaskLogTracking();
                      }
                      this.agentWorkspaceView = 'report';
                      this.activeAgentSessionId = '';
                      this.agentInput = '';
                      this.agentLoading = false;
                      this.agentStatus = 'idle';
                      this.agentAnswer = '';
                      this.agentExecutionTrace = [];
                      this.agentUsedTools = [];
                      this.agentCitations = [];
                      this.agentResearchNotes = [];
                      this.agentClarificationQuestion = '';
                      this.agentRiskPrompt = '';
                      this.agentError = '';
                      this.agentRiskConfirmations = [];
                      this.agentMessages = [];
                      this.agentThinkingTimeline = [];
                      this.agentStreamingMessageId = '';
                      this.agentStreamState = 'idle';
                      this.agentStreamStartedAt = 0;
                      this.agentStreamElapsedTick = 0;
                      this.agentStreamElapsedTimer = null;
                      this.agentThinkingExpanded = false;
                      this.agentSessions = [];
                      this.agentSessionsLoaded = false;
                      this.agentSessionsLoading = false;
                      this.agentSessionHydrating = false;
                      this.agentSessionDetailLoadingId = '';
                      this.agentSessionDetailRequestToken = 0;
                      this.agentTurnAbortController = null;
                      this.agentRunRegistry = {};
                      this.agentSessionMenuId = '';
                      this.agentRenameDialogOpen = false;
                      this.agentRenameSessionId = '';
                      this.agentRenameInput = '';
                      this.agentTools = [];
                      this.agentToolsLoaded = false;
                      this.agentToolsLoading = false;
                      this.agentToolsError = '';
                      this.summaryTaskLogTrackers = {};
                  },
                  async generateH3Grid() {
                      const rawRing = this.getIsochronePolygonRing();
                      if (!rawRing || this.isGeneratingGrid || this.isComputingH3Analysis) return;
  
                      this.isGeneratingGrid = true;
                      this.resetH3AnalysisState();
                      this.h3GridStatus = '正在生成网络...';
                      try {
                          const polygon = this.getIsochronePolygonPayload();
  
                          const res = await fetch('/api/v1/analysis/h3-grid', {
                              method: 'POST',
                              headers: { 'Content-Type': 'application/json' },
                              body: JSON.stringify({
                                  polygon: polygon,
                                  resolution: this.h3GridResolution,
                                  coord_type: 'gcj02',
                                  include_mode: this.h3GridIncludeMode,
                                  min_overlap_ratio: this.h3GridIncludeMode === 'intersects'
                                      ? this.h3GridMinOverlapRatio
                                      : 0
                              })
                          });
                          if (!res.ok) {
                              let detail = '';
                              try {
                                  detail = await res.text();
                              } catch (_) { }
                              throw new Error(detail || '网络生成失败');
                          }
  
                          const data = await res.json();
                          this.h3GridFeatures = data.features || [];
                          this.h3GridCount = Number.isFinite(data.count) ? data.count : this.h3GridFeatures.length;
  
                          if (this.isH3DisplayActive() && this.mapCore && this.mapCore.setGridFeatures) {
                              this.mapCore.setGridFeatures(this.h3GridFeatures, {
                                  strokeColor: '#2c6ecb',
                                  strokeWeight: 1.1,
                                  fillOpacity: 0,
                                  webglBatch: true,
                              });
                          } else {
                              this.clearH3GridDisplayOnLeave();
                          }
                          const baseStatus = this.h3GridCount > 0
                              ? `已生成 ${this.h3GridCount} 个 POI H3 网格`
                              : '已生成网络，但当前范围无可用网格';
                          this.h3GridStatus = this.isH3DisplayActive()
                              ? baseStatus
                              : `${baseStatus}（已就绪，切换到“网格”查看）`;
                      } catch (e) {
                          console.error(e);
                          this.h3GridStatus = '网络生成失败: ' + e.message;
                      } finally {
                          this.isGeneratingGrid = false;
                      }
                  },
                  isRoadSyntaxPanelActive() {
                      return this.step === 2 && this.activeStep3Panel === 'syntax';
                  },
                  isRoadSyntaxMetricViewActive() {
                      return this.isRoadSyntaxPanelActive() && this.roadSyntaxMainTab !== 'params';
                  },
                  roadSyntaxMap() {
                      return (this.mapCore && this.mapCore.map) ? this.mapCore.map : null;
                  },
                  roadSyntaxQuantizeChannel(value, step = 24) {
                      const safe = Number.isFinite(Number(value)) ? Number(value) : 0;
                      const safeStep = Math.max(1, Number(step) || 1);
                      return Math.max(0, Math.min(255, Math.round(safe / safeStep) * safeStep));
                  },
                  roadSyntaxQuantizeHexColor(color = '', step = 24) {
                      const raw = String(color || '').trim();
                      const hex = raw.startsWith('#') ? raw.slice(1) : raw;
                      if (!/^[0-9a-fA-F]{6}$/.test(hex)) return '#9ca3af';
                      const r = this.roadSyntaxQuantizeChannel(parseInt(hex.slice(0, 2), 16), step);
                      const g = this.roadSyntaxQuantizeChannel(parseInt(hex.slice(2, 4), 16), step);
                      const b = this.roadSyntaxQuantizeChannel(parseInt(hex.slice(4, 6), 16), step);
                      return `#${r.toString(16).padStart(2, '0')}${g.toString(16).padStart(2, '0')}${b.toString(16).padStart(2, '0')}`;
                  },
                  roadSyntaxNormalizeLayerStyleForBucket(style = null) {
                      const raw = style || {};
                      const colorStep = Math.max(1, Number(this.roadSyntaxStyleBucketColorStep || 24));
                      const weightStep = Math.max(0.1, Number(this.roadSyntaxStyleBucketWeightStep || 0.5));
                      const opacityStep = Math.max(0.02, Number(this.roadSyntaxStyleBucketOpacityStep || 0.08));
                      const strokeWeightRaw = Number(raw.strokeWeight);
                      const strokeOpacityRaw = Number(raw.strokeOpacity);
                      const zIndexRaw = Number(raw.zIndex);
                      return {
                          strokeColor: this.roadSyntaxQuantizeHexColor(raw.strokeColor || '#9ca3af', colorStep),
                          strokeWeight: Math.max(1, Math.round((Number.isFinite(strokeWeightRaw) ? strokeWeightRaw : 1.8) / weightStep) * weightStep),
                          strokeOpacity: Math.max(0.08, Math.min(1, Math.round((Number.isFinite(strokeOpacityRaw) ? strokeOpacityRaw : 0.32) / opacityStep) * opacityStep)),
                          zIndex: Number.isFinite(zIndexRaw) ? Math.round(zIndexRaw) : 90,
                      };
                  },
                  roadSyntaxBuildLayerStyleBucketKey(style = null) {
                      const s = this.roadSyntaxNormalizeLayerStyleForBucket(style);
                      return `${s.strokeColor}|${s.strokeWeight}|${s.strokeOpacity}|${s.zIndex}`;
                  },
                  roadSyntaxCloneIndexSet(setLike = null) {
                      const out = {};
                      const source = setLike && typeof setLike === 'object' ? setLike : {};
                      Object.keys(source).forEach((key) => {
                          const idx = Number(key);
                          if (!Number.isFinite(idx) || idx < 0) return;
                          out[idx] = true;
                      });
                      return out;
                  },
                  roadSyntaxBuildLayerLodIndexSet(layerKey = '') {
                      const key = String(layerKey || '');
                      const cache = Object.assign({}, this.roadSyntaxLayerLodIndexCache || {});
                      if (cache[key]) {
                          return this.roadSyntaxCloneIndexSet(cache[key]);
                      }
                      const items = Array.isArray(this.roadSyntaxPolylineItems) ? this.roadSyntaxPolylineItems : [];
                      if (!items.length) return {};
  
                      const parsed = this.parseRoadSyntaxLayerKey(key);
                      const metric = parsed.metric || this.resolveRoadSyntaxActiveMetric();
                      const radiusLabel = parsed.radiusLabel || 'global';
                      const metricField = this.resolveRoadSyntaxMetricField(metric, radiusLabel);
                      const fallbackField = this.resolveRoadSyntaxFallbackField(metric);
                      const rankField = this.resolveRoadSyntaxRankField(metric);
                      const scored = [];
                      for (let idx = 0; idx < items.length; idx += 1) {
                          const item = items[idx] || {};
                          const coords = Array.isArray(item.coords) ? item.coords : [];
                          if (coords.length < 2) continue;
                          const props = item.props || {};
                          const rank = Number(rankField ? props[rankField] : NaN);
                          const mainScore = Number(props[metricField]);
                          const fallbackScore = Number(props[fallbackField]);
                          const score = Number.isFinite(rank)
                              ? this.clamp01(rank)
                              : (Number.isFinite(mainScore)
                                  ? this.clamp01(mainScore)
                                  : (Number.isFinite(fallbackScore) ? this.clamp01(fallbackScore) : 0));
                          scored.push({ idx, score });
                      }
                      if (!scored.length) return {};
                      scored.sort((a, b) => (b.score - a.score) || (a.idx - b.idx));
  
                      const cap = Math.max(80, Math.floor(Number(this.roadSyntaxLayerLodCap || 180)));
                      const selected = [];
                      if (scored.length <= cap) {
                          scored.forEach((it) => selected.push(it.idx));
                      } else {
                          const headCount = Math.max(1, Math.min(cap, Math.floor(cap * 0.75)));
                          for (let i = 0; i < headCount; i += 1) {
                              selected.push(scored[i].idx);
                          }
                          const remain = cap - selected.length;
                          if (remain > 0) {
                              const tail = scored.slice(headCount);
                              const step = tail.length / remain;
                              for (let i = 0; i < remain; i += 1) {
                                  const pickIdx = Math.min(tail.length - 1, Math.floor(i * step));
                                  selected.push(tail[pickIdx].idx);
                              }
                          }
                      }
                      const out = {};
                      selected.forEach((idx) => {
                          const n = Number(idx);
                          if (!Number.isFinite(n) || n < 0) return;
                          out[n] = true;
                      });
                      cache[key] = out;
                      this.roadSyntaxLayerLodIndexCache = cache;
                      return this.roadSyntaxCloneIndexSet(out);
                  },
                  roadSyntaxResolveDesiredLayerVariant() {
                      const total = Array.isArray(this.roadSyntaxPolylineItems) ? this.roadSyntaxPolylineItems.length : 0;
                      if (!total) return 'full';
                      if (typeof this.roadSyntaxResolveLodPolicy !== 'function') return 'full';
                      const policy = this.roadSyntaxResolveLodPolicy(total);
                      return (policy && policy.backboneOnly) ? 'lod' : 'full';
                  },
                  roadSyntaxResolveLayerRuntimeEntry(layer = null, variant = 'full') {
                      const requested = String(variant || 'full');
                      const base = layer && typeof layer === 'object' ? layer : null;
                      if (!base) return null;
                      if (requested === 'lod' && base.lodLayer && Array.isArray(base.lodLayer.overlays) && base.lodLayer.overlays.length) {
                          return base.lodLayer;
                      }
                      return base;
                  },
                  roadSyntaxApplyVisibleIndexSet(indexSet = {}, reason = '') {
                      const normalized = this.roadSyntaxCloneIndexSet(indexSet);
                      this.roadSyntaxTargetVisibleLineSet = Object.assign({}, normalized);
                      this.roadSyntaxAppliedVisibleLineSet = Object.assign({}, normalized);
                      this.roadSyntaxOverlayCommitToken = Number(this.roadSyntaxOverlayCommitToken || 0) + 1;
                      this.roadSyntaxOverlayLastCommitPath = 'pool_state_apply';
                      this.roadSyntaxOverlayLastCommitReason = String(reason || 'switch');
                  },
                  roadSyntaxDisposeLayerEntry(layer = null, mapRef = null) {
                      if (!layer) return;
                      const map = mapRef || this.roadSyntaxMap();
                      if (layer.overlayGroup) {
                          this.roadSyntaxSetOverlayGroupVisible(layer.overlayGroup, false, map);
                      }
                      const overlays = Array.isArray(layer.overlays) ? layer.overlays : [];
                      if (overlays.length) {
                          this.roadSyntaxSetLinesVisible(overlays, false, map, { preferBatch: true });
                      }
                      if (layer.lodLayer) {
                          this.roadSyntaxDisposeLayerEntry(layer.lodLayer, map);
                      }
                  },
                  roadSyntaxBuildLayerFromStyles(layerKey = '', styles = [], options = {}) {
                      const items = Array.isArray(this.roadSyntaxPolylineItems) ? this.roadSyntaxPolylineItems : [];
                      const includeIndexSet = (options && options.includeIndexSet && typeof options.includeIndexSet === 'object')
                          ? options.includeIndexSet
                          : null;
                      const variant = String((options && options.variant) || 'full');
                      const zIndexBoost = Number((options && options.zIndexBoost) || 0);
                      const buckets = Object.create(null);
                      let featureCount = 0;
                      const indexSet = {};
                      let invalidPathCount = 0;
                      let polylineCreateErrorCount = 0;
                      const invalidPathSamples = [];
                      for (let idx = 0; idx < items.length; idx += 1) {
                          if (includeIndexSet && !includeIndexSet[idx]) continue;
                          const item = items[idx] || {};
                          const coords = Array.isArray(item.coords) ? item.coords : [];
                          if (coords.length < 2) continue;
                          featureCount += 1;
                          indexSet[idx] = true;
                          const rawStyle = this.roadSyntaxNormalizeLayerStyleForBucket(styles[idx] || null);
                          const style = zIndexBoost
                              ? Object.assign({}, rawStyle, { zIndex: (Number(rawStyle.zIndex) || 90) + zIndexBoost })
                              : rawStyle;
                          const bucketKey = this.roadSyntaxBuildLayerStyleBucketKey(style);
                          if (!buckets[bucketKey]) {
                              buckets[bucketKey] = { style, paths: [] };
                          }
                          buckets[bucketKey].paths.push(coords);
                      }
                      const overlays = [];
                      const bucketValues = Object.values(buckets);
                      bucketValues.forEach((bucket) => {
                          const style = bucket.style || {};
                          const pathsRaw = Array.isArray(bucket.paths) ? bucket.paths : [];
                          if (!pathsRaw.length || !window.AMap) return;
                          const safePaths = [];
                          pathsRaw.forEach((path, pIdx) => {
                              const safePath = this.normalizePath(path, 2, 'road_syntax.layer_build.path');
                              if (!safePath.length) {
                                  invalidPathCount += 1;
                                  if (invalidPathSamples.length < 5) {
                                      invalidPathSamples.push({
                                          layer_key: String(layerKey || ''),
                                          variant: String(variant || ''),
                                          path_index: pIdx,
                                          sample: this.roadSyntaxSummarizeCoordInput(Array.isArray(path) ? path[0] : path)
                                      });
                                  }
                                  return;
                              }
                              safePaths.push(safePath);
                          });
                          if (!safePaths.length) return;
                          safePaths.forEach((safePath) => {
                              try {
                                  const line = markRaw(new AMap.Polyline({
                                      path: safePath,
                                      strokeColor: style.strokeColor || '#9ca3af',
                                      strokeWeight: Number(style.strokeWeight) || 1.8,
                                      strokeOpacity: Number(style.strokeOpacity) || 0.32,
                                      zIndex: Number(style.zIndex) || 90,
                                      bubble: true,
                                      clickable: false,
                                      cursor: 'default',
                                  }));
                                  overlays.push(line);
                              } catch (_) {
                                  polylineCreateErrorCount += 1;
                              }
                          });
                      });
                      if (invalidPathCount > 0 || polylineCreateErrorCount > 0) {
                          console.warn('[road-syntax] layer build skipped invalid paths', {
                              layer_key: String(layerKey || ''),
                              variant: String(variant || ''),
                              invalid_path_count: invalidPathCount,
                              polyline_create_error_count: polylineCreateErrorCount,
                              sample_paths: invalidPathSamples
                          });
                      }
                      let overlayGroup = null;
                      try {
                          if (window.AMap && typeof AMap.OverlayGroup === 'function' && overlays.length) {
                              overlayGroup = markRaw(new AMap.OverlayGroup(overlays));
                          }
                      } catch (_) {
                          overlayGroup = null;
                      }
                      return {
                          layerKey: String(layerKey || ''),
                          mode: 'bucket_pool',
                          variant: variant,
                          overlays,
                          overlayGroup,
                          bucketCount: bucketValues.length,
                          featureCount,
                          indexSet,
                      };
                  },
                  roadSyntaxGetLayer(layerKey = '') {
                      const pool = this.roadSyntaxLayerPool || {};
                      const key = String(layerKey || '');
                      return key ? (pool[key] || null) : null;
                  },
                  roadSyntaxSetStatus(text = '') {
                      this.roadSyntaxStatus = String(text || '');
                  },
                  cancelRoadSyntaxRequest(reason = '') {
                      const controller = this.roadSyntaxFetchAbortController;
                      if (!controller) return false;
                      try {
                          controller.abort();
                      } catch (_) { }
                      this.roadSyntaxFetchAbortController = null;
                      if (reason) {
                          console.info('[road-syntax] request aborted', { reason: String(reason || '') });
                      }
                      return true;
                  },
                  roadSyntaxCreateRunId() {
                      const rand = Math.random().toString(36).slice(2, 10);
                      return `rs_${Date.now()}_${rand}`;
                  },
                  roadSyntaxStopProgressTracking() {
                      if (this.roadSyntaxProgressPollTimer) {
                          window.clearInterval(this.roadSyntaxProgressPollTimer);
                          this.roadSyntaxProgressPollTimer = null;
                      }
                      if (this.roadSyntaxProgressTickTimer) {
                          window.clearInterval(this.roadSyntaxProgressTickTimer);
                          this.roadSyntaxProgressTickTimer = null;
                      }
                      this.roadSyntaxProgressPolling = false;
                  },
                  roadSyntaxResetProgressState() {
                      this.roadSyntaxStopProgressTracking();
                      this.roadSyntaxProgressRunId = '';
                      this.roadSyntaxProgressStage = '';
                      this.roadSyntaxProgressMessage = '';
                      this.roadSyntaxProgressStep = 0;
                      this.roadSyntaxProgressTotal = 0;
                      this.roadSyntaxProgressElapsedSec = 0;
                      this.roadSyntaxProgressStartedAtMs = 0;
                  },
                  async roadSyntaxPollProgressOnce(requestToken = null) {
                      const runId = String(this.roadSyntaxProgressRunId || '').trim();
                      if (!runId) return;
                      if (this.roadSyntaxProgressPolling) return;
                      if (requestToken !== null && requestToken !== this.roadSyntaxRequestToken) return;
                      this.roadSyntaxProgressPolling = true;
                      try {
                          const resp = await fetch(`/api/v1/analysis/road-syntax/progress?run_id=${encodeURIComponent(runId)}`, {
                              cache: 'no-store',
                          });
                          if (!resp.ok) return;
                          const data = await resp.json();
                          const stage = String(data && data.stage || '');
                          const message = String(data && data.message || '');
                          const status = String(data && data.status || 'running');
                          const step = Number(data && data.step);
                          const total = Number(data && data.total);
                          const elapsedSec = Number(data && data.elapsed_sec);
                          this.roadSyntaxProgressStage = stage;
                          this.roadSyntaxProgressMessage = message;
                          this.roadSyntaxProgressStep = Number.isFinite(step) ? Math.max(0, Math.floor(step)) : 0;
                          this.roadSyntaxProgressTotal = Number.isFinite(total) ? Math.max(0, Math.floor(total)) : 0;
                          if (Number.isFinite(elapsedSec) && elapsedSec >= 0) {
                              this.roadSyntaxProgressElapsedSec = elapsedSec;
                          }
                          if (message) {
                              const showStep = this.roadSyntaxProgressStep > 0 && this.roadSyntaxProgressTotal > 0;
                              const withStep = showStep ? `进度 ${this.roadSyntaxProgressStep}/${this.roadSyntaxProgressTotal}：${message}` : message;
                              this.roadSyntaxSetStatus(withStep);
                          }
                          if (status !== 'running') {
                              this.roadSyntaxStopProgressTracking();
                          }
                      } catch (_) {
                      } finally {
                          this.roadSyntaxProgressPolling = false;
                      }
                  },
                  roadSyntaxStartProgressTracking(runId, requestToken = null, initialMessage = '已提交计算请求') {
                      this.roadSyntaxStopProgressTracking();
                      this.roadSyntaxProgressRunId = String(runId || '').trim();
                      this.roadSyntaxProgressStage = 'queued';
                      this.roadSyntaxProgressMessage = String(initialMessage || '');
                      this.roadSyntaxProgressStep = 0;
                      this.roadSyntaxProgressTotal = 9;
                      this.roadSyntaxProgressStartedAtMs = Date.now();
                      this.roadSyntaxProgressElapsedSec = 0;
                      if (initialMessage) {
                          this.roadSyntaxSetStatus(initialMessage);
                      }
                      if (!this.roadSyntaxProgressRunId) return;
                      this.roadSyntaxProgressTickTimer = window.setInterval(() => {
                          if (!this.isComputingRoadSyntax) return;
                          if (!this.roadSyntaxProgressStartedAtMs) return;
                          const sec = Math.max(0, Math.floor((Date.now() - this.roadSyntaxProgressStartedAtMs) / 1000));
                          this.roadSyntaxProgressElapsedSec = sec;
                      }, 1000);
                      this.roadSyntaxProgressPollTimer = window.setInterval(() => {
                          this.roadSyntaxPollProgressOnce(requestToken);
                      }, 1000);
                      this.roadSyntaxPollProgressOnce(requestToken);
                  },
                  roadSyntaxUseLegacyPoolStatus() {
                      return false;
                  },
                  roadSyntaxLogOverlayHealth(reason = '', options = {}) {
                      const force = !!(options && options.force);
                      const throttleMs = Math.max(0, Number((options && options.throttleMs) || 1200));
                      const now = this.roadSyntaxNow();
                      const lastAt = Number(this._roadSyntaxOverlayHealthLastAt || 0);
                      if (!force && (now - lastAt) < throttleMs) {
                          return null;
                      }
                      this._roadSyntaxOverlayHealthLastAt = now;
                      if (
                          this.roadSyntaxUseArcgisWebgl
                          && this.roadSyntaxWebglActive
                          && this.roadSyntaxWebglPayload
                      ) {
                          const webglCount = Number((((this.roadSyntaxWebglPayload || {}).roads || {}).count) || 0);
                          if (force || webglCount <= 0) {
                              console.info('[road-syntax] overlay pool health', {
                                  reason: String(reason || ''),
                                  active_layer: String(this.roadSyntaxActiveLayerKey || ''),
                                  visible_lines: webglCount,
                                  applied_visible_lines: webglCount,
                                  target_visible_lines: webglCount,
                                  total_lines: webglCount,
                                  mode: 'arcgis_webgl',
                              });
                          }
                          return {
                              inspectedLines: webglCount,
                              visibleLines: webglCount,
                              invalid: { path: 0, endpoint: 0, line: 0 },
                              totalLines: webglCount,
                          };
                      }
                      const appliedSet = (this.roadSyntaxAppliedVisibleLineSet && typeof this.roadSyntaxAppliedVisibleLineSet === 'object')
                          ? this.roadSyntaxAppliedVisibleLineSet
                          : {};
                      const targetSet = (this.roadSyntaxTargetVisibleLineSet && typeof this.roadSyntaxTargetVisibleLineSet === 'object')
                          ? this.roadSyntaxTargetVisibleLineSet
                          : {};
                      const totalCount = Array.isArray(this.roadSyntaxPolylineItems) ? this.roadSyntaxPolylineItems.length : 0;
                      const appliedCount = Object.keys(appliedSet).length;
                      const targetCount = Object.keys(targetSet).length;
                      const visibleCount = appliedCount > 0
                          ? appliedCount
                          : (this.roadSyntaxActiveLayerKey ? totalCount : 0);
                      if (force || visibleCount <= 0) {
                          console.info('[road-syntax] overlay pool health', {
                              reason: String(reason || ''),
                              active_layer: String(this.roadSyntaxActiveLayerKey || ''),
                              visible_lines: visibleCount,
                              applied_visible_lines: appliedCount,
                              target_visible_lines: targetCount,
                              total_lines: totalCount,
                              mode: 'bucket_pool',
                          });
                      }
                      return {
                          inspectedLines: visibleCount,
                          visibleLines: visibleCount,
                          invalid: { path: 0, endpoint: 0, line: 0 },
                          totalLines: totalCount,
                      };
                  },
                  invalidateRoadSyntaxCache(reason = 'manual', options = {}) {
                      const resetData = !!(options && options.resetData);
                      const resetPerf = !!(options && options.resetPerf);
                      if (typeof this.roadSyntaxClearMapWriteQueue === 'function') {
                          this.roadSyntaxClearMapWriteQueue({ dispose: reason === 'unmount' });
                      }
                      this.roadSyntaxStyleUpdateToken += 1;
                      this.roadSyntaxPoolWarmToken += 1;
                      this.roadSyntaxLayerBuildToken += 1;
                      this.roadSyntaxLayerSwitchToken += 1;
                      this.roadSyntaxPrewarmToken += 1;
                      this.roadSyntaxStyleApplyToken += 1;
                      this.roadSyntaxSwitchInProgress = false;
                      this.roadSyntaxSwitchQueuedLayerKey = '';
                      this.roadSyntaxSwitchLastAt = 0;
                      this.roadSyntaxClearSwitchThrottleTimer();
                      this.roadSyntaxClearViewportRefreshHandles();
                      this.roadSyntaxClearNodeRefreshTimer();
                      this.roadSyntaxBumpViewportRefreshToken();
                      this._roadSyntaxPinnedAttachKey = '';
                      this._roadSyntaxViewportToggleDisabledLogged = false;
                      this.roadSyntaxOverlayCommitToken = 0;
                      this.roadSyntaxOverlayLastCommitPath = '';
                      this.roadSyntaxOverlayLastCommitReason = '';
                      this.roadSyntaxInteractionLowFidelity = false;
                      this.roadSyntaxDisplaySuspended = false;
                      this.clearRoadSyntaxLayerPool();
                      this.roadSyntaxPolylines = [];
                      this.roadSyntaxPolylineItems = [];
                      this.roadSyntaxResetVisibleIndexCache();
                      this.roadSyntaxResetLodScoreCache();
                      this.roadSyntaxResetSpatialIndex();
                      this.roadSyntaxSourceFingerprint = '';
                      this.roadSyntaxPoolRadiusLabel = '';
                      this.roadSyntaxLastStyleKey = '';
                      this.roadSyntaxConnectivityReuseLayerKey = '';
                      this.roadSyntaxNodeBuildToken += 1;
                      this.roadSyntaxNodeBuildRunning = false;
                      this.roadSyntaxNodeSourceFingerprint = '';
                      this.clearRoadSyntaxNodeMarkers({ immediate: true });
                      this.disposeRoadSyntaxScatterChart();
                      this.roadSyntaxWebglPayload = null;
                      this.roadSyntaxWebglStatus = '';
                      this.roadSyntaxWebglRadiusFilterCache = null;
                      if (typeof this.clearRoadSyntaxArcgisWebgl === 'function') {
                          this.clearRoadSyntaxArcgisWebgl({ dispose: reason === 'unmount' });
                      }
                      if (resetData) {
                          this.roadSyntaxStatus = '';
                          this.roadSyntaxSummary = null;
                          this.roadSyntaxRoadFeatures = [];
                          this.roadSyntaxNodes = [];
                          this.roadSyntaxDiagnostics = null;
                          this.roadSyntaxScatterPointsCache = [];
                          this.roadSyntaxLegendModel = null;
                          this.roadSyntaxSkeletonOnly = false;
                          this.roadSyntaxMainTab = 'params';
                          const defaultMetric = this.roadSyntaxDefaultMetric();
                          this.roadSyntaxMetric = defaultMetric;
                          this.roadSyntaxLastMetricTab = defaultMetric;
                          this.roadSyntaxRadiusLabel = 'global';
                      }
                      if (resetPerf) {
                          this.roadSyntaxSwitchSamples = [];
                          this.roadSyntaxSwitchLastMs = 0;
                          this.roadSyntaxSwitchP50Ms = 0;
                          this.roadSyntaxSwitchP95Ms = 0;
                          this.roadSyntaxSwitchStatsText = '';
                          this.roadSyntaxSwitchPath = '';
                      }
                      if (reason === 'unmount') {
                          this.roadSyntaxStatus = '';
                      }
                  },
                  resetRoadSyntaxState() {
                      this.roadSyntaxRequestToken += 1;
                      this.isComputingRoadSyntax = false;
                      this.roadSyntaxResetProgressState();
                      this.invalidateRoadSyntaxCache('reset-state', { resetData: true, resetPerf: true });
                  },
                  clearRoadSyntaxOverlays() {
                      this.invalidateRoadSyntaxCache('clear-overlays', { resetData: false, resetPerf: false });
                  },
                  suspendRoadSyntaxDisplay() {
                      const map = this.roadSyntaxMap();
                      if (!map) return;
                      this.roadSyntaxDisplaySuspended = true;
                      this.roadSyntaxLayerSwitchToken += 1;
                      this.roadSyntaxClearViewportRefreshHandles();
                      this.roadSyntaxClearNodeRefreshTimer();
                      this.roadSyntaxBumpViewportRefreshToken();
                      this._roadSyntaxPinnedAttachKey = '';
                      this.roadSyntaxInteractionLowFidelity = false;
                      const activeLayer = this.roadSyntaxGetLayer(this.roadSyntaxActiveLayerKey || '');
                      const activeRuntime = this.roadSyntaxResolveLayerRuntimeEntry(activeLayer, this.roadSyntaxActiveLayerVariant || 'full');
                      if (activeRuntime) {
                          if (activeRuntime.overlayGroup) {
                              this.roadSyntaxSetOverlayGroupVisible(activeRuntime.overlayGroup, false, map);
                          } else if (Array.isArray(activeRuntime.overlays) && activeRuntime.overlays.length) {
                              this.roadSyntaxSetLinesVisible(activeRuntime.overlays, false, map, { preferBatch: true });
                          }
                      }
                      this.roadSyntaxResetVisibleIndexCache();
                      this.roadSyntaxCurrentStride = 1;
                      if (typeof this.setRoadSyntaxArcgisWebglVisible === 'function') {
                          this.setRoadSyntaxArcgisWebglVisible(false);
                      }
                      this.cancelRoadSyntaxNodeBuild();
                      this.setRoadSyntaxNodeMarkersVisible(false);
                      this.disposeRoadSyntaxScatterChart();
                  },
                  resumeRoadSyntaxDisplay() {
                      if (
                          !this.roadSyntaxSummary
                          || !Array.isArray(this.roadSyntaxRoadFeatures)
                          || !this.roadSyntaxRoadFeatures.length
                      ) {
                          this.roadSyntaxDisplaySuspended = false;
                          return;
                      }
                      if (
                          this.roadSyntaxUseArcgisWebgl
                          && typeof this.roadSyntaxCanUseArcgisWebglPayload === 'function'
                          && this.roadSyntaxCanUseArcgisWebglPayload(this.roadSyntaxWebglPayload)
                      ) {
                          this.roadSyntaxDisplaySuspended = false;
                          this.renderRoadSyntaxByMetric(this.resolveRoadSyntaxActiveMetric());
                          return;
                      }
                      if (this.roadSyntaxStrictWebglOnly) {
                          this.roadSyntaxDisplaySuspended = false;
                          this.roadSyntaxSetStatus(this.buildRoadSyntaxWebglUnavailableMessage(this.roadSyntaxWebglPayload));
                          return;
                      }
                      this._roadSyntaxPinnedAttachKey = '';
                      this.roadSyntaxDisplaySuspended = true;
                      this.renderRoadSyntaxOverlays({
                          type: 'FeatureCollection',
                          features: this.roadSyntaxRoadFeatures,
                      }, { forceRebuild: false, displayActive: true });
                  },
                  clearRoadSyntaxLayerPool() {
                      const map = this.roadSyntaxMap();
                      const lines = Array.isArray(this.roadSyntaxPolylines) ? this.roadSyntaxPolylines : [];
                      this.roadSyntaxSetLinesVisible(lines, false, map, { preferBatch: true });
                      this.roadSyntaxClearViewportRefreshHandles();
                      this.roadSyntaxClearNodeRefreshTimer();
                      const pool = this.roadSyntaxLayerPool || {};
                      Object.keys(pool).forEach((key) => {
                          this.roadSyntaxDisposeLayerEntry(pool[key], map);
                      });
                      this.roadSyntaxLayerPool = {};
                      this.roadSyntaxLayerStyleCache = {};
                      this.roadSyntaxLayerLodIndexCache = {};
                      this.roadSyntaxPolylines = [];
                      this.roadSyntaxTargetVisibleLineSet = {};
                      this.roadSyntaxAppliedVisibleLineSet = {};
                      this.roadSyntaxResetVisibleIndexCache();
                      this.roadSyntaxResetLodScoreCache();
                      this.roadSyntaxResetSpatialIndex();
                      this.roadSyntaxBumpViewportRefreshToken();
                      this.roadSyntaxInteractionLowFidelity = false;
                      this.roadSyntaxCurrentStride = 1;
                      this.roadSyntaxActiveLayerKey = '';
                      this.roadSyntaxActiveLayerVariant = 'full';
                      this.roadSyntaxPendingLayerKey = '';
                      this.roadSyntaxLayerBuildState = {};
                      this.roadSyntaxLayerBuildQueue = [];
                      this.roadSyntaxLayerBuildRunning = false;
                      this.roadSyntaxPoolInitRunning = false;
                      this.roadSyntaxPoolReady = false;
                      this.roadSyntaxPoolDegraded = false;
                      this.roadSyntaxPoolInitTotal = 0;
                      this.roadSyntaxPoolInitDone = 0;
                      this.roadSyntaxLayerReadyMap = {};
                      this.roadSyntaxConnectivityReuseLayerKey = '';
                  },
                  refreshRoadSyntaxLayerReadyMap() {
                      const keys = this.roadSyntaxLayerKeysForPrebuild();
                      const state = this.roadSyntaxLayerBuildState || {};
                      const cache = this.roadSyntaxLayerStyleCache || {};
                      const readyMap = {};
                      keys.forEach((key) => {
                          readyMap[key] = !!cache[key] && state[key] === 'ready';
                      });
                      this.roadSyntaxLayerReadyMap = readyMap;
                      this.roadSyntaxPoolInitTotal = keys.length;
                      this.roadSyntaxPoolInitDone = Object.values(readyMap).filter((v) => !!v).length;
                      return readyMap;
                  },
                  isRoadSyntaxMetricReady(metricValue = null, options = {}) {
                      if (!this.roadSyntaxSummary) return false;
                      const metric = String(metricValue || this.resolveRoadSyntaxActiveMetric() || this.roadSyntaxDefaultMetric());
                      if (this.roadSyntaxStrictWebglOnly) {
                          return !!(
                              this.roadSyntaxUseArcgisWebgl
                              && typeof this.roadSyntaxCanUseArcgisWebglPayload === 'function'
                              && this.roadSyntaxCanUseArcgisWebglPayload(this.roadSyntaxWebglPayload)
                          );
                      }
                      if (
                          this.roadSyntaxUseArcgisWebgl
                          && typeof this.roadSyntaxCanUseArcgisWebglPayload === 'function'
                          && this.roadSyntaxCanUseArcgisWebglPayload(this.roadSyntaxWebglPayload)
                      ) {
                          return true;
                      }
                      const radiusLabel = options && Object.prototype.hasOwnProperty.call(options, 'radiusLabel')
                          ? String(options.radiusLabel || 'global')
                          : (this.roadSyntaxMetricUsesRadius(metric) ? String(this.roadSyntaxRadiusLabel || 'global') : 'global');
                      const skeletonOnly = options && Object.prototype.hasOwnProperty.call(options, 'skeletonOnly')
                          ? !!options.skeletonOnly
                          : false;
                      const key = this.resolveRoadSyntaxLayerKey(metric, { radiusLabel, skeletonOnly });
                      return this.isRoadSyntaxLayerReady(key);
                  },
                  canActivateRoadSyntaxTab(tabValue) {
                      const tab = String(tabValue || '').trim();
                      if (tab === 'params') return true;
                      if (!this.roadSyntaxSummary) return false;
                      return this.isRoadSyntaxMetricReady(tab);
                  },
                  canToggleRoadSyntaxSkeleton() {
                      const metric = this.resolveRoadSyntaxActiveMetric();
                      if (!this.roadSyntaxSupportsSkeleton(metric)) return false;
                      if (!this.roadSyntaxSummary) return false;
                      if (
                          this.roadSyntaxUseArcgisWebgl
                          && typeof this.roadSyntaxCanUseArcgisWebglPayload === 'function'
                          && this.roadSyntaxCanUseArcgisWebglPayload(this.roadSyntaxWebglPayload)
                      ) {
                          return false;
                      }
                      if (!this.roadSyntaxSkeletonOnly) {
                          return this.isRoadSyntaxMetricReady(metric, { skeletonOnly: true });
                      }
                      return this.isRoadSyntaxMetricReady(metric, { skeletonOnly: false });
                  },
                  cancelRoadSyntaxNodeBuild() {
                      this.roadSyntaxNodeBuildToken += 1;
                      this.roadSyntaxNodeBuildRunning = false;
                  },
                  shouldRenderRoadSyntaxConnectivityNodes() {
                      if (!this.mapCore || !this.mapCore.map) return false;
                      const minZoom = Number(this.roadSyntaxConnectivityNodeMinZoom || 15);
                      const zoom = Number(this.mapCore.map.getZoom ? this.mapCore.map.getZoom() : NaN);
                      if (!Number.isFinite(zoom)) return true;
                      return zoom >= minZoom;
                  },
                  setRoadSyntaxNodeMarkersVisible(visible) {
                      if (!Array.isArray(this.roadSyntaxNodeMarkers) || !this.roadSyntaxNodeMarkers.length) {
                          return;
                      }
                      if (visible && !this.shouldRenderRoadSyntaxConnectivityNodes()) {
                          visible = false;
                      }
                      const markers = this.roadSyntaxNodeMarkers.slice();
                      const targetMap = (visible && this.mapCore && this.mapCore.map) ? this.mapCore.map : null;
                      this.roadSyntaxEnqueueMapWrite(() => {
                          markers.forEach((marker) => this.safeMapSet(marker, targetMap));
                          return {
                              ok: true,
                                  marker_count: markers.length,
                                  visible: !!targetMap
                              };
                      }, {
                          key: 'road_syntax_node_visibility',
                          replaceExisting: true,
                          meta: {
                              reason: 'road_syntax_node_visibility',
                              marker_count: markers.length,
                              visible: !!targetMap
                          }
                      });
                  },
                  clearRoadSyntaxNodeMarkers(options = {}) {
                      this.cancelRoadSyntaxNodeBuild();
                      if (!Array.isArray(this.roadSyntaxNodeMarkers)) {
                          this.roadSyntaxNodeMarkers = [];
                          return;
                      }
                      const immediate = !!(options && options.immediate);
                      const markers = this.roadSyntaxNodeMarkers.slice();
                      this.roadSyntaxNodeMarkers = [];
                      if (!markers.length) return;
                      if (immediate) {
                          markers.forEach((marker) => this.safeMapSet(marker, null));
                          return;
                      }
                      this.roadSyntaxEnqueueMapWrite(() => {
                          markers.forEach((marker) => this.safeMapSet(marker, null));
                          return {
                              ok: true,
                              marker_count: markers.length
                          };
                      }, {
                          key: 'road_syntax_node_clear',
                          replaceExisting: false,
                          meta: {
                              reason: 'road_syntax_node_clear',
                              marker_count: markers.length
                          }
                      });
                  },
                  disposeRoadSyntaxScatterChart() {
                      this.clearRoadSyntaxScatterRenderTimer();
                      const chart = this.roadSyntaxScatterChart;
                      if (chart && typeof chart.dispose === 'function') {
                          chart.dispose();
                      }
                      this.roadSyntaxScatterChart = null;
                  },
                  clearRoadSyntaxScatterRenderTimer() {
                      if (this.roadSyntaxScatterRenderTimer) {
                          window.clearTimeout(this.roadSyntaxScatterRenderTimer);
                          this.roadSyntaxScatterRenderTimer = null;
                      }
                  },
                  scheduleRoadSyntaxScatterRender(attempt = 0) {
                      if (this.roadSyntaxMainTab !== 'intelligibility') return;
                      const retry = Math.max(0, Number(attempt) || 0);
                      const maxRetry = 8;
                      this.clearRoadSyntaxScatterRenderTimer();
                      const delay = retry === 0 ? 0 : Math.min(180, 40 + retry * 20);
                      this.roadSyntaxScatterRenderTimer = window.setTimeout(() => {
                          this.roadSyntaxScatterRenderTimer = null;
                          const rendered = this.renderRoadSyntaxScatterChart();
                          if (!rendered && retry < maxRetry && this.roadSyntaxMainTab === 'intelligibility') {
                              this.scheduleRoadSyntaxScatterRender(retry + 1);
                          }
                      }, delay);
                  },
                  setRoadSyntaxMainTab(tabValue, options = {}) {
                      const value = String(tabValue || '').trim();
                      const validTabs = (this.roadSyntaxTabs || []).map((tab) => tab.value);
                      if (!validTabs.includes(value)) return;
                      if (value !== 'params' && this.roadSyntaxPoolInitRunning && this.roadSyntaxUseLegacyPoolStatus()) {
                          this.roadSyntaxSetStatus(this.roadSyntaxFormatReadyStatus('图层预加载中', this.roadSyntaxPoolInitDone, this.roadSyntaxPoolInitTotal || 0));
                          return;
                      }
                      const syncMetric = options.syncMetric !== false;
                      const refresh = options.refresh !== false;
                      const previousTab = this.roadSyntaxMainTab;
                      const previousMetric = this.roadSyntaxMetric;
                      this.roadSyntaxMainTab = value;
                      if (value === 'params') {
                          this.cancelRoadSyntaxNodeBuild();
                          this.setRoadSyntaxNodeMarkersVisible(false);
                          this.disposeRoadSyntaxScatterChart();
                          if (this.mapCore && typeof this.mapCore.setRadius === 'function') {
                              this.mapCore.setRadius(0);
                          }
                          return;
                      }
                      if (!this.isRoadSyntaxMetricReady(value)) {
                          if (this.roadSyntaxStrictWebglOnly) {
                              this.roadSyntaxSetStatus(`指标“${this.roadSyntaxLabelByMetric(value)}”对应 ArcGIS-WebGL 数据未就绪`);
                          } else {
                              const counts = this.roadSyntaxLayerReadyCounts();
                              if (this.roadSyntaxPoolDegraded) {
                                  this.roadSyntaxSetStatus(`图层预处理已降级，指标“${this.roadSyntaxLabelByMetric(value)}”仍未就绪（${counts.ready}/${counts.total || 0}）`);
                              } else {
                                  this.roadSyntaxSetStatus(`指标“${this.roadSyntaxLabelByMetric(value)}”仍在预处理（${counts.ready}/${counts.total || 0}）`);
                              }
                          }
                          return;
                      }
                      if (syncMetric) {
                          this.roadSyntaxMetric = value;
                          this.roadSyntaxLastMetricTab = value;
                      }
                      if (!this.roadSyntaxMetricUsesRadius(value)) {
                          this.roadSyntaxRadiusLabel = 'global';
                      } else if (!this.roadSyntaxHasRadiusLabel(this.roadSyntaxRadiusLabel)) {
                          this.roadSyntaxRadiusLabel = 'global';
                      }
                      this.roadSyntaxApplyRadiusCircle(value);
                      if (previousTab === value && previousMetric === this.roadSyntaxMetric) {
                          return;
                      }
                      if (refresh) {
                          this.refreshRoadSyntaxOverlay();
                      }
                  },
                  roadSyntaxMetricTabs() {
                      return (this.roadSyntaxTabs || []).filter((item) => item.value !== 'params');
                  },
                  roadSyntaxDefaultMetric() {
                      const tabs = this.roadSyntaxMetricTabs();
                      if (tabs.length) {
                          return String((tabs[0] && tabs[0].value) || 'connectivity');
                      }
                      return 'connectivity';
                  },
                  roadSyntaxMetricDataCount(metricValue = null) {
                      const metric = String(metricValue || this.resolveRoadSyntaxActiveMetric() || this.roadSyntaxDefaultMetric());
                      const summary = this.roadSyntaxSummary || {};
                      if (metric === 'control') return Number(summary.control_valid_count || 0);
                      if (metric === 'depth') return Number(summary.depth_valid_count || 0);
                      return Number(summary.edge_count || 0);
                  },
                  isRoadSyntaxMetricAvailable(metricValue = null) {
                      const metric = String(metricValue || this.resolveRoadSyntaxActiveMetric() || this.roadSyntaxDefaultMetric());
                      if (metric !== 'control' && metric !== 'depth') return true;
                      return this.roadSyntaxMetricDataCount(metric) > 0;
                  },
                  roadSyntaxLabelByMetric(metricValue) {
                      const metric = String(metricValue || '').trim();
                      const matched = this.roadSyntaxMetricTabs().find((item) => item.value === metric);
                      return matched ? matched.label : metric;
                  },
                  roadSyntaxMetricUsesRadius(metricValue = null) {
                      const metric = metricValue || this.roadSyntaxMetric || this.roadSyntaxDefaultMetric();
                      return metric === 'choice' || metric === 'integration';
                  },
                  roadSyntaxSupportsSkeleton(metricValue = null) {
                      void metricValue;
                      return false;
                  },
                  onRoadSyntaxMetricChange(metricValue) {
                      this.setRoadSyntaxMainTab(metricValue);
                  },
                  formatRoadSyntaxMetricValue(metricValue) {
                      const summary = this.roadSyntaxSummary || {};
                      const metric = metricValue || this.roadSyntaxDefaultMetric();
                      if (!this.isRoadSyntaxMetricAvailable(metric)) return '--';
                      let value = NaN;
                      if (metric === 'accessibility') {
                          value = Number(summary.avg_accessibility_global ?? summary.avg_closeness);
                      } else if (metric === 'connectivity') {
                          value = Number(summary.avg_connectivity ?? summary.avg_degree);
                      } else if (metric === 'control') {
                          value = Number(summary.avg_control);
                      } else if (metric === 'depth') {
                          value = Number(summary.avg_depth);
                      } else if (metric === 'choice') {
                          const radiusLabel = this.roadSyntaxNormalizeRadiusLabel(this.roadSyntaxRadiusLabel, metric);
                          const byRadius = (summary.avg_choice_by_radius && typeof summary.avg_choice_by_radius === 'object')
                              ? summary.avg_choice_by_radius
                              : {};
                          value = radiusLabel === 'global'
                              ? Number(summary.avg_choice_global)
                              : Number(byRadius[radiusLabel]);
                          if (!Number.isFinite(value)) {
                              value = Number(summary.avg_choice_global);
                          }
                      } else if (metric === 'integration') {
                          const radiusLabel = this.roadSyntaxNormalizeRadiusLabel(this.roadSyntaxRadiusLabel, metric);
                          const byRadius = (summary.avg_integration_by_radius && typeof summary.avg_integration_by_radius === 'object')
                              ? summary.avg_integration_by_radius
                              : {};
                          value = radiusLabel === 'global'
                              ? Number(summary.avg_integration_global)
                              : Number(byRadius[radiusLabel]);
                          if (!Number.isFinite(value)) {
                              value = Number(summary.avg_integration_global);
                          }
                      } else if (metric === 'intelligibility') {
                          value = Number(summary.avg_intelligibility);
                      }
                      if (!Number.isFinite(value)) return '--';
                      if (metric === 'connectivity') return value.toFixed(2);
                      if (metric === 'intelligibility') return value.toFixed(4);
                      return value.toFixed(6);
                  },
                  roadSyntaxRadiusOptions() {
                      const labelsRaw = (this.roadSyntaxSummary && Array.isArray(this.roadSyntaxSummary.radius_labels))
                          ? this.roadSyntaxSummary.radius_labels
                          : [];
                      const labels = labelsRaw.map((item) => String(item || '').trim().toLowerCase());
                      const out = [{ value: 'global', label: '等时圈内' }];
                      if (labels.includes('r600')) {
                          out.push({ value: 'r600', label: '600m' });
                      }
                      if (labels.includes('r800')) {
                          out.push({ value: 'r800', label: '800m' });
                      }
                      return out;
                  },
                  roadSyntaxHasRadiusLabel(radiusLabel) {
                      const target = String(radiusLabel || '').trim().toLowerCase();
                      if (!target) return false;
                      return this.roadSyntaxRadiusOptions().some((opt) => String(opt.value) === target);
                  },
                  roadSyntaxNormalizeRadiusLabel(radiusLabel, metricValue = null) {
                      const metric = metricValue || this.resolveRoadSyntaxActiveMetric();
                      const target = String(radiusLabel || 'global').trim().toLowerCase();
                      if (this.roadSyntaxMetricUsesRadius(metric) && this.roadSyntaxHasRadiusLabel(target)) {
                          return target;
                      }
                      return 'global';
                  },
                  roadSyntaxRadiusMeters(radiusLabel = null, metricValue = null) {
                      const label = this.roadSyntaxNormalizeRadiusLabel(
                          radiusLabel == null ? this.roadSyntaxRadiusLabel : radiusLabel,
                          metricValue
                      );
                      if (label === 'r600') return 600;
                      if (label === 'r800') return 800;
                      return 0;
                  },
                  roadSyntaxApplyRadiusCircle(metricValue = null) {
                      const metric = metricValue || this.resolveRoadSyntaxActiveMetric();
                      let radiusMeters = 0;
                      if (this.roadSyntaxMetricUsesRadius(metric)) {
                          radiusMeters = this.roadSyntaxRadiusMeters(this.roadSyntaxRadiusLabel, metric);
                      }
                      const centerReady = !!(
                          this.selectedPoint
                          && Number.isFinite(Number(this.selectedPoint.lng))
                          && Number.isFinite(Number(this.selectedPoint.lat))
                      );
                      if (this.mapCore && typeof this.mapCore.setRadius === 'function') {
                          this.mapCore.setRadius((radiusMeters > 0 && centerReady) ? radiusMeters : 0);
                      }
                  },
                  setRoadSyntaxRadiusLabel(radiusLabel) {
                      const metric = this.resolveRoadSyntaxActiveMetric();
                      if (!this.roadSyntaxMetricUsesRadius(metric)) return;
                      const nextLabel = this.roadSyntaxNormalizeRadiusLabel(radiusLabel, metric);
                      if (!this.roadSyntaxHasRadiusLabel(nextLabel)) return;
                      if (nextLabel === String(this.roadSyntaxRadiusLabel || 'global')) {
                          this.roadSyntaxApplyRadiusCircle(metric);
                          return;
                      }
                      this.roadSyntaxRadiusLabel = nextLabel;
                      this.roadSyntaxApplyRadiusCircle(metric);
                      this.refreshRoadSyntaxOverlay();
                  },
                  normalizeRoadSyntaxGraphModel(model = null) {
                      const raw = String(
                          model == null
                              ? this.roadSyntaxGraphModel
                              : model
                      ).trim().toLowerCase();
                      return raw === 'axial' ? 'axial' : 'segment';
                  },
                  roadSyntaxGraphModelLabel(model = null) {
                      const normalized = this.normalizeRoadSyntaxGraphModel(model);
                      return normalized === 'axial' ? '轴线图' : '线段图';
                  },
                  async fetchRoadSyntaxApi(payload, options = {}) {
                      const signal = options && options.signal ? options.signal : undefined;
                      const res = await fetch('/api/v1/analysis/road-syntax', {
                          method: 'POST',
                          headers: { 'Content-Type': 'application/json' },
                          body: JSON.stringify(payload),
                          signal,
                      });
                      if (!res.ok) {
                          let detail = '';
                          try {
                              const body = await res.json();
                              if (body && typeof body === 'object') {
                                  if (typeof body.detail === 'string' && body.detail.trim()) {
                                      detail = body.detail.trim();
                                  } else {
                                      detail = JSON.stringify(body);
                                  }
                              }
                          } catch (_) {
                              try {
                                  detail = await res.text();
                              } catch (_) { }
                          }
                          throw new Error(detail || '路网分析失败');
                      }
                      return await res.json();
                  },
                  async applyRoadSyntaxDataset(data, preferredMetricTab = 'connectivity') {
                      this.invalidateRoadSyntaxCache('switch-road-syntax-scope', { resetData: false, resetPerf: false });
                      this.applyRoadSyntaxResponseData(data, preferredMetricTab);
                      if (!this.roadSyntaxSummary) return;
                      const targetMetric = this.roadSyntaxLastMetricTab || this.roadSyntaxMetric || this.roadSyntaxDefaultMetric();
                      this.setRoadSyntaxMainTab(targetMetric, {
                          refresh: false,
                          syncMetric: true,
                      });
                      if (this.isRoadSyntaxPanelActive()) {
                          await this.renderRoadSyntaxByMetric(targetMetric);
                      }
                  },
                  resolveRoadSyntaxRequestMetric() {
                      return this.roadSyntaxMetric === 'choice' ? 'choice' : 'integration';
                  },
                  clamp01(value) {
                      return Math.max(0, Math.min(1, Number(value) || 0));
                  },
                  blendTwoColor(colorA, colorB, ratio) {
                      const a = Array.isArray(colorA) ? colorA : [0, 0, 0];
                      const b = Array.isArray(colorB) ? colorB : [0, 0, 0];
                      const t = this.clamp01(ratio);
                      const r = Math.round(a[0] + (b[0] - a[0]) * t);
                      const g = Math.round(a[1] + (b[1] - a[1]) * t);
                      const b2 = Math.round(a[2] + (b[2] - a[2]) * t);
                      const toHex = (c) => {
                          const hex = Math.max(0, Math.min(255, c)).toString(16);
                          return hex.length === 1 ? '0' + hex : hex;
                      };
                      return `#${toHex(r)}${toHex(g)}${toHex(b2)}`;
                  },
                  blendPaletteColor(stops, ratio) {
                      const palette = Array.isArray(stops) && stops.length ? stops : [[0, 0, 0], [255, 255, 255]];
                      const t = this.clamp01(ratio);
                      const toHex = (c) => {
                          const hex = Math.max(0, Math.min(255, c)).toString(16);
                          return hex.length === 1 ? '0' + hex : hex;
                      };
                      if (palette.length === 1) {
                          const c = palette[0];
                          return `#${toHex(c[0])}${toHex(c[1])}${toHex(c[2])}`;
                      }
                      const seg = Math.min(palette.length - 2, Math.floor(t * (palette.length - 1)));
                      const segStart = seg / (palette.length - 1);
                      const segEnd = (seg + 1) / (palette.length - 1);
                      const local = (t - segStart) / Math.max(1e-9, segEnd - segStart);
                      return this.blendTwoColor(palette[seg], palette[seg + 1], local);
                  },
                  onRoadSyntaxDisplayRangeChange() {
                      const blue = this.clamp01(Number(this.roadSyntaxDisplayBlue));
                      const red = this.clamp01(Number(this.roadSyntaxDisplayRed));
                      this.roadSyntaxDisplayBlue = Number.isFinite(blue) ? blue : 0;
                      this.roadSyntaxDisplayRed = Number.isFinite(red) ? red : 1;
                      if (this.roadSyntaxMainTab !== 'params') {
                          this.refreshRoadSyntaxOverlay();
                      }
                  },
                  roadSyntaxDepthmapColorSchemes() {
                      return {
                          axmanesque: [
                              '#3333dd', '#3388dd', '#22ccdd', '#22ccbb', '#22dd88',
                              '#88dd22', '#bbcc22', '#ddcc22', '#dd8833', '#dd3333',
                          ],
                          hueonlyaxmanesque: [
                              '#3333dd', '#3377dd', '#33bbdd', '#33ddbb', '#33dd55',
                              '#55dd33', '#bbdd33', '#ddbb33', '#dd7733', '#dd3333',
                          ],
                          bluered: [
                              '#4575b4', '#91bfdb', '#e0f3f8', '#ffffbf', '#fee090', '#fc8d59', '#d73027',
                          ],
                          purpleorange: [
                              '#542788', '#998ec3', '#d8daeb', '#f7f7f7', '#fee0b6', '#f1a340', '#b35806',
                          ],
                          greyscale: [
                              '#000000', '#444444', '#777777', '#aaaaaa', '#cccccc', '#eeeeee', '#ffffff',
                          ],
                          monochrome: [
                              '#000000', '#444444', '#777777', '#aaaaaa', '#cccccc', '#eeeeee', '#ffffff',
                          ],
                      };
                  },
                  roadSyntaxDepthmapColorScaleOptions() {
                      return [
                          { value: 'axmanesque', label: 'Equal Ranges (3-Colour)' },
                          { value: 'bluered', label: 'Equal Ranges (Blue-Red)' },
                          { value: 'purpleorange', label: 'Equal Ranges (Purple-Orange)' },
                          { value: 'depthmapclassic', label: 'depthmapX Classic' },
                          { value: 'greyscale', label: 'Equal Ranges (Greyscale)' },
                          { value: 'monochrome', label: 'Equal Ranges (Monochrome)' },
                          { value: 'hueonlyaxmanesque', label: 'Equal Ranges (3-Colour Hue Only)' },
                      ];
                  },
                  roadSyntaxDepthmapColorScaleLabel() {
                      const current = String(this.roadSyntaxDepthmapColorScale || 'axmanesque');
                      const options = this.roadSyntaxDepthmapColorScaleOptions();
                      const matched = options.find((opt) => String(opt.value) === current);
                      return matched ? matched.label : 'Equal Ranges (3-Colour)';
                  },
                  roadSyntaxDepthmapDisplayParams() {
                      const rawBlue = this.clamp01(Number(this.roadSyntaxDisplayBlue));
                      const rawRed = this.clamp01(Number(this.roadSyntaxDisplayRed));
                      let blue = rawBlue;
                      let red = rawRed;
                      let inverted = false;
                      if (blue > red) {
                          inverted = true;
                          blue = 1.0 - rawBlue;
                          red = 1.0 - rawRed;
                      }
                      return {
                          rawBlue,
                          rawRed,
                          blue: this.clamp01(blue),
                          red: this.clamp01(red),
                          inverted,
                      };
                  },
                  roadSyntaxDepthmapPalette() {
                      const schemes = this.roadSyntaxDepthmapColorSchemes();
                      const key = String(this.roadSyntaxDepthmapColorScale || 'axmanesque').toLowerCase();
                      return Array.isArray(schemes[key]) && schemes[key].length
                          ? schemes[key]
                          : schemes.axmanesque;
                  },
                  roadSyntaxDepthmapClassIndex(field, classCount) {
                      const count = Math.max(1, Number(classCount) || 1);
                      const t = this.clamp01(field);
                      const raw = Math.floor((t - 1e-9) * count);
                      return Math.max(0, Math.min(count - 1, raw));
                  },
                  roadSyntaxDepthmapScaledField(field) {
                      if (!Number.isFinite(Number(field))) return NaN;
                      const scale = String(this.roadSyntaxDepthmapColorScale || 'axmanesque').toLowerCase();
                      const params = this.roadSyntaxDepthmapDisplayParams();
                      let value = this.clamp01(Number(field));
                      if (params.inverted) {
                          value = 1.0 - value;
                      }
                      if (scale === 'depthmapclassic') {
                          return value;
                      }
                      const denom = params.red - params.blue;
                      if (!(denom > 1e-9)) {
                          return 0.5;
                      }
                      const scaled = (value - params.blue) / denom;
                      if (!Number.isFinite(scaled)) return 0.5;
                      return this.clamp01(scaled);
                  },
                  roadSyntaxNormalizeScoreByRange(value, minValue, maxValue) {
                      const v = Number(value);
                      const lo = Number(minValue);
                      const hi = Number(maxValue);
                      if (!Number.isFinite(v)) return 0;
                      if (!Number.isFinite(lo) || !Number.isFinite(hi) || hi <= lo) return this.clamp01(v);
                      return this.clamp01((v - lo) / Math.max(1e-9, hi - lo));
                  },
                  roadSyntaxDepthmapClassicByte(value) {
                      const v = this.clamp01(value);
                      const scaled = Math.floor((v + 0.0333) * 15.0);
                      return Math.max(0, Math.min(255, scaled * 17));
                  },
                  roadSyntaxDepthmapClassicColor(score, blueValue = null, redValue = null) {
                      const field = this.clamp01(score);
                      const params = this.roadSyntaxDepthmapDisplayParams();
                      const blue = Number.isFinite(Number(blueValue)) ? this.clamp01(Number(blueValue)) : params.blue;
                      const red = Number.isFinite(Number(redValue)) ? this.clamp01(Number(redValue)) : params.red;
                      const green = blue + (red - blue) / 10.0;
                      let r = 0;
                      let g = 0;
                      let b = 0;
                      if (field >= 0.0 && field < blue) {
                          r = this.roadSyntaxDepthmapClassicByte(0.5 * (blue - field) / Math.max(1e-9, blue));
                          b = 255;
                      } else if (field >= blue && field < (green + blue) / 2.0) {
                          b = 255;
                          g = this.roadSyntaxDepthmapClassicByte(2.0 * (field - blue) / Math.max(1e-9, green - blue));
                      } else if (field >= (green + blue) / 2.0 && field < green) {
                          b = this.roadSyntaxDepthmapClassicByte(2.0 * (green - field) / Math.max(1e-9, green - blue));
                          g = 255;
                      } else if (field >= green && field < (green + red) / 2.0) {
                          g = 255;
                          r = this.roadSyntaxDepthmapClassicByte(2.0 * (field - green) / Math.max(1e-9, red - green));
                      } else if (field >= (green + red) / 2.0 && field < red) {
                          g = this.roadSyntaxDepthmapClassicByte(2.0 * (red - field) / Math.max(1e-9, red - green));
                          r = 255;
                      } else {
                          r = 255;
                          b = this.roadSyntaxDepthmapClassicByte(0.5 * (field - red) / Math.max(1e-9, 1.0 - red));
                      }
                      const toHex = (c) => {
                          const hex = Math.max(0, Math.min(255, Number(c) || 0)).toString(16);
                          return hex.length === 1 ? `0${hex}` : hex;
                      };
                      return `#${toHex(r)}${toHex(g)}${toHex(b)}`;
                  },
                  roadSyntaxDepthmapClassColor(score, paletteValue = null) {
                      const palette = Array.isArray(paletteValue) && paletteValue.length
                          ? paletteValue
                          : this.roadSyntaxDepthmapPalette();
                      const scale = String(this.roadSyntaxDepthmapColorScale || 'axmanesque').toLowerCase();
                      if (!Number.isFinite(Number(score))) {
                          if (scale === 'monochrome' || scale === 'greyscale') {
                              return 'rgba(0,0,0,0)';
                          }
                          return '#7f7f7f';
                      }
                      const scaledField = this.roadSyntaxDepthmapScaledField(score);
                      if (scale === 'depthmapclassic') {
                          const params = this.roadSyntaxDepthmapDisplayParams();
                          return this.roadSyntaxDepthmapClassicColor(scaledField, params.blue, params.red);
                      }
                      const idx = this.roadSyntaxDepthmapClassIndex(scaledField, palette.length);
                      return String(palette[idx] || '#3333dd');
                  },
                  roadSyntaxEqualRangeLegendItems(scores, paletteValue = null) {
                      const scale = String(this.roadSyntaxDepthmapColorScale || 'axmanesque').toLowerCase();
                      const palette = Array.isArray(paletteValue) && paletteValue.length
                          ? paletteValue
                          : this.roadSyntaxDepthmapPalette();
                      const legendColors = (scale === 'depthmapclassic')
                          ? new Array(10).fill(0).map((_, idx) => this.roadSyntaxDepthmapClassColor((idx + 0.5) / 10, palette))
                          : palette;
                      const values = (Array.isArray(scores) ? scores : [])
                          .map((v) => Number(v))
                          .filter((v) => Number.isFinite(v))
                          .sort((a, b) => a - b);
                      if (!values.length) {
                          return legendColors.map((color, idx) => ({ color, label: `等级 ${idx + 1}` }));
                      }
                      const min = values[0];
                      const max = values[values.length - 1];
                      if (!(max > min)) {
                          return legendColors.map((color, idx) => ({
                              color,
                              label: idx === 0 ? `${min.toFixed(2)}` : '-',
                          }));
                      }
                      const span = max - min;
                      const colors = legendColors;
                      const params = this.roadSyntaxDepthmapDisplayParams();
                      return colors.map((color, idx) => {
                          let loField = idx / colors.length;
                          let hiField = (idx + 1) / colors.length;
                          if (scale !== 'depthmapclassic') {
                              loField = params.blue + (params.red - params.blue) * loField;
                              hiField = params.blue + (params.red - params.blue) * hiField;
                          }
                          const lo = min + span * this.clamp01(loField);
                          const hi = min + span * this.clamp01(hiField);
                          return {
                              color,
                              label: `${lo.toFixed(2)} - ${hi.toFixed(2)}`,
                          };
                      });
                  },
                  roadSyntaxSummarizeCoordInput(input) {
                      if (input === null) return { type: 'null' };
                      if (typeof input === 'undefined') return { type: 'undefined' };
                      if (typeof input === 'string') return { type: 'string', value: String(input).slice(0, 80) };
                      if (Array.isArray(input)) {
                          return {
                              type: 'array',
                              length: input.length,
                              head: input.slice(0, 2),
                          };
                      }
                      if (typeof input === 'object') {
                          const out = { type: 'object' };
                          if (Object.prototype.hasOwnProperty.call(input, 'lng')) out.lng = input.lng;
                          if (Object.prototype.hasOwnProperty.call(input, 'lat')) out.lat = input.lat;
                          if (Object.prototype.hasOwnProperty.call(input, 'lon')) out.lon = input.lon;
                          if (typeof input.getLng === 'function') out.getLng = true;
                          if (typeof input.getLat === 'function') out.getLat = true;
                          return out;
                      }
                      return { type: typeof input, value: input };
                  },
                  roadSyntaxLogInvalidCoordInput(source = '', input = null) {
                      const key = String(source || 'unknown');
                      if (!this._roadSyntaxInvalidCoordStats) {
                          this._roadSyntaxInvalidCoordStats = Object.create(null);
                      }
                      const stats = this._roadSyntaxInvalidCoordStats;
                      if (!stats[key]) {
                          stats[key] = { count: 0 };
                      }
                      stats[key].count += 1;
                      const count = stats[key].count;
                      if (count <= 5) {
                          console.warn('[road-syntax] invalid coordinate input', {
                              source: key,
                              count: count,
                              sample: this.roadSyntaxSummarizeCoordInput(input)
                          });
                      } else if (count % 100 === 0) {
                          console.warn('[road-syntax] invalid coordinate input aggregated', {
                              source: key,
                              count: count
                          });
                      }
                  },
                  normalizeLngLat(input, source = '') {
                      let lng = NaN;
                      let lat = NaN;
                      if (Array.isArray(input) && input.length >= 2) {
                          lng = Number(input[0]);
                          lat = Number(input[1]);
                      } else if (input && typeof input === 'object') {
                          if (typeof input.getLng === 'function' && typeof input.getLat === 'function') {
                              lng = Number(input.getLng());
                              lat = Number(input.getLat());
                          } else if (Object.prototype.hasOwnProperty.call(input, 'lng') && Object.prototype.hasOwnProperty.call(input, 'lat')) {
                              lng = Number(input.lng);
                              lat = Number(input.lat);
                          } else if (Object.prototype.hasOwnProperty.call(input, 'lon') && Object.prototype.hasOwnProperty.call(input, 'lat')) {
                              lng = Number(input.lon);
                              lat = Number(input.lat);
                          }
                      } else if (typeof input === 'string') {
                          const parts = input.split(',');
                          if (parts.length >= 2) {
                              lng = Number(parts[0].trim());
                              lat = Number(parts[1].trim());
                          }
                      }
                      if (!Number.isFinite(lng) || !Number.isFinite(lat)) {
                          this.roadSyntaxLogInvalidCoordInput(source || 'normalize_lnglat', input);
                          return null;
                      }
                      if (lng < -180 || lng > 180 || lat < -90 || lat > 90) {
                          this.roadSyntaxLogInvalidCoordInput(source || 'normalize_lnglat_range', {
                              input: this.roadSyntaxSummarizeCoordInput(input),
                              lng,
                              lat
                          });
                          return null;
                      }
                      return [lng, lat];
                  },
                  normalizePath(path, minPoints = 2, source = '') {
                      const raw = Array.isArray(path) ? path : [];
                      const out = [];
                      raw.forEach((pt) => {
                          const loc = this.normalizeLngLat(pt, source || 'normalize_path');
                          if (!loc) return;
                          out.push(loc);
                      });
                      return out.length >= minPoints ? out : [];
                  },
                  resolveRoadSyntaxActiveMetric() {
                      const defaultMetric = this.roadSyntaxDefaultMetric();
                      const validMetrics = this.roadSyntaxMetricTabs().map((item) => String(item.value || ''));
                      const candidate = this.roadSyntaxMainTab === 'params'
                          ? (this.roadSyntaxLastMetricTab || this.roadSyntaxMetric)
                          : this.roadSyntaxMetric;
                      const normalized = String(candidate || '').trim();
                      if (validMetrics.includes(normalized)) return normalized;
                      const backup = String(this.roadSyntaxMetric || '').trim();
                      if (validMetrics.includes(backup)) return backup;
                      return defaultMetric;
                  },
                  resolveRoadSyntaxMetricField(metricValue = null, radiusLabelValue = null) {
                      const metric = metricValue || this.resolveRoadSyntaxActiveMetric();
                      const radiusLabel = this.roadSyntaxNormalizeRadiusLabel(
                          radiusLabelValue == null ? this.roadSyntaxRadiusLabel : radiusLabelValue,
                          metric
                      );
                      if (metric === 'connectivity') {
                          return 'connectivity_score';
                      }
                      if (metric === 'control') {
                          return 'control_score';
                      }
                      if (metric === 'depth') {
                          return 'depth_score';
                      }
                      if (metric === 'intelligibility') {
                          return 'intelligibility_score';
                      }
                      if (metric === 'choice') {
                          return radiusLabel === 'global' ? 'choice_global' : `choice_${radiusLabel}`;
                      }
                      if (metric === 'integration') {
                          return radiusLabel === 'global' ? 'integration_global' : `integration_${radiusLabel}`;
                      }
                      return 'connectivity_score';
                  },
                  resolveRoadSyntaxLayerKey(metricValue = null, options = {}) {
                      const metric = metricValue || this.resolveRoadSyntaxActiveMetric();
                      const skeletonOnly = options && Object.prototype.hasOwnProperty.call(options, 'skeletonOnly')
                          ? !!options.skeletonOnly
                          : !!this.roadSyntaxSkeletonOnly;
                      const radiusLabelRaw = options && Object.prototype.hasOwnProperty.call(options, 'radiusLabel')
                          ? String(options.radiusLabel || 'global')
                          : (this.roadSyntaxMetricUsesRadius(metric) ? String(this.roadSyntaxRadiusLabel || 'global') : 'global');
                      const radiusLabel = this.roadSyntaxNormalizeRadiusLabel(radiusLabelRaw, metric);
                      const supportsSkeleton = typeof this.roadSyntaxSupportsSkeleton === 'function'
                          ? !!this.roadSyntaxSupportsSkeleton(metric)
                          : (metric === 'choice' || metric === 'integration');
                      const useSkeleton = supportsSkeleton ? skeletonOnly : false;
                      const normalizedRadius = this.roadSyntaxMetricUsesRadius(metric) ? radiusLabel : 'global';
                      return `${metric}|${normalizedRadius}|${useSkeleton ? 1 : 0}`;
                  },
                  parseRoadSyntaxLayerKey(layerKey) {
                      const parts = String(layerKey || '').split('|');
                      const metric = parts[0] || this.roadSyntaxDefaultMetric();
                      const radiusLabel = parts[1] || 'global';
                      const skeletonOnly = parts[2] === '1';
                      return { metric, radiusLabel, skeletonOnly };
                  },
                  roadSyntaxLayerKeysForPrebuild() {
                      const radiusLabels = this.roadSyntaxRadiusOptions().map((opt) => String(opt.value || 'global'));
                      const choiceKeys = radiusLabels.map((radiusLabel) => this.resolveRoadSyntaxLayerKey('choice', { radiusLabel, skeletonOnly: false }));
                      const integrationKeys = radiusLabels.map((radiusLabel) => this.resolveRoadSyntaxLayerKey('integration', { radiusLabel, skeletonOnly: false }));
                      return [
                          this.resolveRoadSyntaxLayerKey('connectivity', { radiusLabel: 'global', skeletonOnly: false }),
                          this.resolveRoadSyntaxLayerKey('control', { radiusLabel: 'global', skeletonOnly: false }),
                          this.resolveRoadSyntaxLayerKey('depth', { radiusLabel: 'global', skeletonOnly: false }),
                          ...choiceKeys,
                          ...integrationKeys,
                          this.resolveRoadSyntaxLayerKey('intelligibility', { radiusLabel: 'global', skeletonOnly: false }),
                      ];
                  },
                  resolveRoadSyntaxRankField(activeMetric) {
                      if (activeMetric === 'choice') return 'rank_quantile_choice';
                      if (activeMetric === 'integration') return 'rank_quantile_integration';
                      if (activeMetric === 'accessibility') return 'rank_quantile_accessibility';
                      return '';
                  },
                  roadSyntaxScoreFromProps(props, metricField, fallbackField) {
                      const readField = (field) => {
                          if (!props || typeof props !== 'object') return NaN;
                          if (!Object.prototype.hasOwnProperty.call(props, field)) return NaN;
                          const raw = props[field];
                          if (raw === null || typeof raw === 'undefined' || raw === '') return NaN;
                          const n = Number(raw);
                          return Number.isFinite(n) ? n : NaN;
                      };
                      const main = readField(metricField);
                      const fallback = readField(fallbackField);
                      if (Number.isFinite(main)) return this.clamp01(main);
                      if (Number.isFinite(fallback)) return this.clamp01(fallback);
                      return NaN;
                  },
                  roadSyntaxQuantileBreakLabels(scores) {
                      const values = (Array.isArray(scores) ? scores : [])
                          .map((v) => Number(v))
                          .filter((v) => Number.isFinite(v))
                          .sort((a, b) => a - b);
                      if (!values.length) {
                          return ['P10 --', 'P30 --', 'P70 --', 'P90 --'];
                      }
                      const q = (ratio) => {
                          const t = Math.max(0, Math.min(1, ratio));
                          if (values.length === 1) return values[0];
                          const pos = t * (values.length - 1);
                          const lo = Math.floor(pos);
                          const hi = Math.min(values.length - 1, lo + 1);
                          const f = pos - lo;
                          return values[lo] + (values[hi] - values[lo]) * f;
                      };
                      return [
                          `P10 ${q(0.1).toFixed(2)}`,
                          `P30 ${q(0.3).toFixed(2)}`,
                          `P70 ${q(0.7).toFixed(2)}`,
                          `P90 ${q(0.9).toFixed(2)}`,
                      ];
                  },
                  buildRoadSyntaxLegendModel(activeMetric) {
                      const metric = activeMetric || this.resolveRoadSyntaxActiveMetric();
                      const metricField = this.resolveRoadSyntaxMetricField(metric);
                      const fallbackField = this.resolveRoadSyntaxFallbackField(metric);
                      const palette = this.roadSyntaxDepthmapPalette();
                      const scaleLabel = this.roadSyntaxDepthmapColorScaleLabel();
                      const polylineItems = Array.isArray(this.roadSyntaxPolylineItems) ? this.roadSyntaxPolylineItems : [];
                      let scores = polylineItems
                          .map((item) => this.roadSyntaxScoreFromProps((item && item.props) || {}, metricField, fallbackField));
                      if (!scores.length) {
                          const roadFeatures = Array.isArray(this.roadSyntaxRoadFeatures) ? this.roadSyntaxRoadFeatures : [];
                          scores = roadFeatures
                              .map((feature) => this.roadSyntaxScoreFromProps(((feature && feature.properties) || {}), metricField, fallbackField));
                      }
                      if (metric === 'accessibility') {
                          return {
                              type: 'discrete',
                              title: `可达性（${scaleLabel}）`,
                              items: this.roadSyntaxEqualRangeLegendItems(scores, palette),
                          };
                      }
                      if (metric === 'integration') {
                          return {
                              type: 'discrete',
                              title: `整合度（${scaleLabel}）`,
                              items: this.roadSyntaxEqualRangeLegendItems(scores, palette),
                          };
                      }
                      if (metric === 'choice') {
                          return {
                              type: 'discrete',
                              title: `选择度（${scaleLabel}）`,
                              items: this.roadSyntaxEqualRangeLegendItems(scores, palette),
                          };
                      }
                      if (metric === 'connectivity') {
                          return {
                              type: 'discrete',
                              title: `连接度（${scaleLabel}）`,
                              items: this.roadSyntaxEqualRangeLegendItems(scores, palette),
                          };
                      }
                      if (metric === 'control') {
                          return {
                              type: 'discrete',
                              title: `控制值（${scaleLabel}）`,
                              items: this.roadSyntaxEqualRangeLegendItems(scores, palette),
                          };
                      }
                      if (metric === 'depth') {
                          return {
                              type: 'discrete',
                              title: `深度值（${scaleLabel}）`,
                              items: this.roadSyntaxEqualRangeLegendItems(scores, palette),
                          };
                      }
                      return {
                          type: 'discrete',
                          title: '可理解度（散点回归）',
                          items: [
                              { label: '样本点', color: '#2563eb' },
                              { label: '回归线', color: '#dc2626' },
                          ],
                      };
                  },
                  roadSyntaxFootnoteByMetric(metricValue = null) {
                      const metric = metricValue || this.resolveRoadSyntaxActiveMetric();
                      const scaleLabel = this.roadSyntaxDepthmapColorScaleLabel();
                      const params = this.roadSyntaxDepthmapDisplayParams();
                      const rangeHint = `(Blue=${params.rawBlue.toFixed(2)}, Red=${params.rawRed.toFixed(2)})`;
                      if (metric === 'connectivity') {
                          return `连接度采用 depthmapX ${scaleLabel} ${rangeHint} 的线段着色图表达，不启用节点点层。`;
                      }
                      if (metric === 'control') {
                          const col = String((this.roadSyntaxSummary && this.roadSyntaxSummary.control_source_column) || '');
                          if (!this.isRoadSyntaxMetricAvailable('control')) {
                              return `控制值当前无有效样本${col ? `（列：${col}）` : ''}，请检查 depthmap 输出列与分析参数。`;
                          }
                          if (col === 'topology_fallback') {
                              return `控制值当前采用拓扑回退计算（depthmap 控制列不可用或近常量），用于保障稳定显示。`;
                          }
                          return `控制值采用 depthmapX ${scaleLabel} ${rangeHint} 的线段着色表达。`;
                      }
                      if (metric === 'depth') {
                          if (!this.isRoadSyntaxMetricAvailable('depth')) {
                              const col = String((this.roadSyntaxSummary && this.roadSyntaxSummary.depth_source_column) || '');
                              return `深度值当前无有效样本${col ? `（列：${col}）` : ''}，请检查 depthmap 输出列与分析参数。`;
                          }
                          return `深度值采用 depthmapX ${scaleLabel} ${rangeHint} 的线段着色表达。`;
                      }
                      if (metric === 'choice') {
                          return `选择度采用 depthmapX ${scaleLabel} ${rangeHint} 的线段着色表达。`;
                      }
                      if (metric === 'integration') {
                          return `整合度采用 depthmapX ${scaleLabel} ${rangeHint} 的线段着色表达网络中心性。`;
                      }
                      if (metric === 'intelligibility') {
                          return '可理解度主表达为散点回归图（x=连接度，y=整合度）；地图蓝线为网络参考层。';
                      }
                      return `连接度采用 depthmapX ${scaleLabel} ${rangeHint} 的线段着色表达。`;
                  },
                  roadSyntaxRegressionView() {
                      const diagnostics = this.roadSyntaxDiagnostics || {};
                      const reg = diagnostics.regression || {};
                      const summary = this.roadSyntaxSummary || {};
                      const r = Number(reg.r);
                      const r2 = Number(reg.r2);
                      const n = Number(reg.n);
                      const fallbackR = Number(summary.avg_intelligibility);
                      const fallbackR2 = Number(summary.avg_intelligibility_r2);
                      return {
                          r: Number.isFinite(r) ? r.toFixed(4) : (Number.isFinite(fallbackR) ? fallbackR.toFixed(4) : '--'),
                          r2: Number.isFinite(r2) ? r2.toFixed(4) : (Number.isFinite(fallbackR2) ? fallbackR2.toFixed(4) : '--'),
                          n: Number.isFinite(n) ? String(Math.round(n)) : String((diagnostics.intelligibility_scatter || []).length || 0),
                          slope: Number.isFinite(Number(reg.slope)) ? Number(reg.slope) : 0,
                          intercept: Number.isFinite(Number(reg.intercept)) ? Number(reg.intercept) : 0,
                      };
                  },
                  buildRoadSyntaxStyleForMetric(props, metricField, fallbackField, activeMetric, skeletonOnlyOverride = null) {
                      const score = this.roadSyntaxScoreFromProps(props, metricField, fallbackField);
                      const metric = activeMetric || this.resolveRoadSyntaxActiveMetric();
                      const supportsSkeleton = typeof this.roadSyntaxSupportsSkeleton === 'function'
                          ? !!this.roadSyntaxSupportsSkeleton(metric)
                          : (metric === 'choice' || metric === 'integration');
                      const skeletonOnly = supportsSkeleton && (skeletonOnlyOverride === null ? !!this.roadSyntaxSkeletonOnly : !!skeletonOnlyOverride);
                      const palette = this.roadSyntaxDepthmapPalette();
                      const scale = String(this.roadSyntaxDepthmapColorScale || 'axmanesque').toLowerCase();
                      const depthmapColor = this.roadSyntaxDepthmapClassColor(score, palette);
                      const baseWeight = 2.1;
                      const missingValue = !Number.isFinite(Number(score));
                      const hideMissing = missingValue && (scale === 'monochrome' || scale === 'greyscale');
                      const baseOpacity = hideMissing ? 0.0 : 0.88;
                      if (metric === 'accessibility') {
                          return {
                              strokeColor: depthmapColor,
                              strokeWeight: baseWeight,
                              strokeOpacity: baseOpacity,
                              zIndex: 90,
                          };
                      }
                      if (metric === 'integration') {
                          const isSkeleton = !!(props && props.is_skeleton_integration_top20);
                          if (skeletonOnly && !isSkeleton) {
                              return {
                                  strokeColor: '#a1a1aa',
                                  strokeWeight: 1.5,
                                  strokeOpacity: 0.15,
                                  zIndex: 82,
                              };
                          }
                          return {
                              strokeColor: depthmapColor,
                              strokeWeight: baseWeight,
                              strokeOpacity: baseOpacity,
                              zIndex: 91,
                          };
                      }
                      if (metric === 'choice') {
                          const isSkeleton = !!(props && props.is_skeleton_choice_top20);
                          if (skeletonOnly && !isSkeleton) {
                              return {
                                  strokeColor: '#9ca3af',
                                  strokeWeight: 1.5,
                                  strokeOpacity: 0.15,
                                  zIndex: 82,
                              };
                          }
                          return {
                              strokeColor: depthmapColor,
                              strokeWeight: baseWeight,
                              strokeOpacity: baseOpacity,
                              zIndex: 92,
                          };
                      }
                      if (metric === 'connectivity') {
                          return {
                              strokeColor: depthmapColor,
                              strokeWeight: baseWeight,
                              strokeOpacity: baseOpacity,
                              zIndex: 80,
                          };
                      }
                      if (metric === 'control') {
                          return {
                              strokeColor: depthmapColor,
                              strokeWeight: baseWeight,
                              strokeOpacity: baseOpacity,
                              zIndex: 81,
                          };
                      }
                      if (metric === 'depth') {
                          return {
                              strokeColor: depthmapColor,
                              strokeWeight: baseWeight,
                              strokeOpacity: baseOpacity,
                              zIndex: 81,
                          };
                      }
                      if (metric === 'intelligibility') {
                          return {
                              strokeColor: '#2563eb',
                              strokeWeight: 2.2,
                              strokeOpacity: 0.62,
                              zIndex: 79,
                          };
                      }
                      return {
                          strokeColor: '#9ca3af',
                          strokeWeight: 1.4,
                          strokeOpacity: 0.22,
                          zIndex: 79,
                      };
                  },
                  refreshRoadSyntaxOverlay() {
                      if (this.roadSyntaxMainTab === 'params') {
                          return;
                      }
                      const metric = this.resolveRoadSyntaxActiveMetric();
                      if (metric === 'intelligibility') {
                          const parsedActive = this.parseRoadSyntaxLayerKey(this.roadSyntaxActiveLayerKey || '');
                          const activeMetric = String((parsedActive && parsedActive.metric) || '');
                          const webglActive = (typeof this.roadSyntaxIsArcgisWebglActive === 'function')
                              ? this.roadSyntaxIsArcgisWebglActive()
                              : !!this.roadSyntaxWebglActive;
                          if (webglActive && activeMetric === 'intelligibility') {
                              this.roadSyntaxLegendModel = this.buildRoadSyntaxLegendModel(metric);
                              this.$nextTick(() => this.scheduleRoadSyntaxScatterRender(0));
                              return;
                          }
                      }
                      const supportsSkeleton = this.roadSyntaxSupportsSkeleton(metric);
                      const effectiveSkeletonOnly = supportsSkeleton ? !!this.roadSyntaxSkeletonOnly : false;
                      if (!supportsSkeleton && this.roadSyntaxSkeletonOnly) {
                          this.roadSyntaxSkeletonOnly = false;
                      }
                      const targetReady = this.isRoadSyntaxMetricReady(metric, { skeletonOnly: effectiveSkeletonOnly });
                      if (!targetReady) {
                          if (this.roadSyntaxStrictWebglOnly) {
                              this.roadSyntaxSetStatus(this.buildRoadSyntaxWebglUnavailableMessage(this.roadSyntaxWebglPayload));
                          } else {
                              const counts = this.roadSyntaxLayerReadyCounts();
                              this.roadSyntaxSetStatus(`目标图层仍在预处理（${counts.ready}/${counts.total || 0}）`);
                          }
                          return;
                      }
                      this.renderRoadSyntaxByMetric(this.resolveRoadSyntaxActiveMetric());
                  },
                  async renderRoadSyntaxByMetric(metricValue = null) {
                      const activeMetric = metricValue || this.resolveRoadSyntaxActiveMetric();
                      this.roadSyntaxApplyRadiusCircle(activeMetric);
                      const webglPayloadReady = (
                          this.roadSyntaxUseArcgisWebgl
                          && typeof this.roadSyntaxCanUseArcgisWebglPayload === 'function'
                          && this.roadSyntaxCanUseArcgisWebglPayload(this.roadSyntaxWebglPayload)
                      );
                      if (
                          webglPayloadReady
                          && typeof this.renderRoadSyntaxArcgisWebgl === 'function'
                      ) {
                          let webglRendered = false;
                          try {
                              webglRendered = await this.renderRoadSyntaxArcgisWebgl(this.roadSyntaxWebglPayload, {
                                  hideWhenSuspended: true,
                              });
                          } catch (err) {
                              webglRendered = false;
                              console.warn('[road-syntax] arcgis webgl render failed', err);
                          }
                          if (webglRendered) {
                              this.cancelRoadSyntaxNodeBuild();
                              this.setRoadSyntaxNodeMarkersVisible(false);
                              if (activeMetric === 'intelligibility') {
                                  this.$nextTick(() => this.scheduleRoadSyntaxScatterRender(0));
                              } else {
                                  this.disposeRoadSyntaxScatterChart();
                              }
                              this.roadSyntaxLegendModel = this.buildRoadSyntaxLegendModel(activeMetric);
                              return;
                          }
                      }
                      this.clearRoadSyntaxOverlays();
                      this.roadSyntaxLegendModel = null;
                      this.cancelRoadSyntaxNodeBuild();
                      this.setRoadSyntaxNodeMarkersVisible(false);
                      this.disposeRoadSyntaxScatterChart();
                      if (webglPayloadReady) {
                          const webglReason = String(this.roadSyntaxWebglStatus || '').trim();
                          this.roadSyntaxSetStatus(
                              webglReason
                                  ? `ArcGIS-WebGL 渲染失败（已禁用旧版回退）: ${webglReason}`
                                  : 'ArcGIS-WebGL 渲染失败（已禁用旧版回退）'
                          );
                      } else {
                          this.roadSyntaxSetStatus(this.buildRoadSyntaxWebglUnavailableMessage(this.roadSyntaxWebglPayload));
                      }
                  },
                  resolveRoadSyntaxFallbackField(activeMetric) {
                      let fallbackField = 'connectivity_score';
                      if (activeMetric === 'choice') {
                          fallbackField = 'choice_score';
                      } else if (activeMetric === 'integration') {
                          fallbackField = 'integration_score';
                      } else if (activeMetric === 'connectivity') {
                          fallbackField = 'degree_score';
                      } else if (activeMetric === 'control') {
                          fallbackField = 'control_score';
                      } else if (activeMetric === 'depth') {
                          fallbackField = 'depth_score';
                      } else if (activeMetric === 'intelligibility') {
                          fallbackField = 'intelligibility_score';
                      }
                      return fallbackField;
                  },
                  renderRoadSyntaxNodeMarkers(options = {}) {
                      if (!this.mapCore || !this.mapCore.map || !window.AMap) return;
                      const forceRebuild = !!(options && options.forceRebuild);
                      if (!this.shouldRenderRoadSyntaxConnectivityNodes()) {
                          this.cancelRoadSyntaxNodeBuild();
                          this.setRoadSyntaxNodeMarkersVisible(false);
                          return;
                      }
                      let nodes = Array.isArray(this.roadSyntaxNodes) ? this.roadSyntaxNodes : [];
                      if (!nodes.length) {
                          const fallbackMap = {};
                          (this.roadSyntaxPolylineItems || []).forEach((item) => {
                              const coords = Array.isArray(item && item.coords) ? item.coords : [];
                              const props = (item && item.props) || {};
                              const score = this.clamp01(Number(props.degree_score));
                              const endpoints = [coords[0], coords[coords.length - 1]];
                              endpoints.forEach((pt) => {
                                  const loc = this.normalizeLngLat(pt, 'road_syntax.node_fallback.endpoint');
                                  if (!loc) return;
                                  const key = `${loc[0].toFixed(6)},${loc[1].toFixed(6)}`;
                                  const prev = fallbackMap[key];
                                  if (!prev || score > prev.score) {
                                      fallbackMap[key] = { loc, score };
                                  }
                              });
                          });
                          nodes = Object.keys(fallbackMap).map((key) => ({
                              geometry: { coordinates: fallbackMap[key].loc },
                              properties: {
                                  degree_score: fallbackMap[key].score,
                                  degree: Math.round(fallbackMap[key].score * 10),
                                  integration_global: 0,
                              },
                          }));
                      }
                      if (!nodes.length) {
                          this.clearRoadSyntaxNodeMarkers({ immediate: true });
                          return;
                      }
  
                      const zoom = Number(this.mapCore.map.getZoom ? this.mapCore.map.getZoom() : NaN);
                      let sampledNodes = nodes;
                      if (Number.isFinite(zoom) && zoom < 16 && nodes.length > 2200) {
                          const stride = Math.max(1, Math.ceil(nodes.length / 1800));
                          sampledNodes = nodes.filter((_, idx) => idx % stride === 0);
                      }
  
                      const firstCoord = this.normalizeLngLat((((sampledNodes[0] || {}).geometry || {}).coordinates || []), 'road_syntax.node_fingerprint.first') || [0, 0];
                      const lastCoord = this.normalizeLngLat((((sampledNodes[sampledNodes.length - 1] || {}).geometry || {}).coordinates || []), 'road_syntax.node_fingerprint.last') || [0, 0];
                      const sourceFingerprint = `${sampledNodes.length}|${firstCoord[0].toFixed(6)},${firstCoord[1].toFixed(6)}|${lastCoord[0].toFixed(6)},${lastCoord[1].toFixed(6)}`;
                      if (
                          !forceRebuild &&
                          sourceFingerprint === this.roadSyntaxNodeSourceFingerprint &&
                          Array.isArray(this.roadSyntaxNodeMarkers) &&
                          this.roadSyntaxNodeMarkers.length
                      ) {
                          this.setRoadSyntaxNodeMarkersVisible(true);
                          return;
                      }
  
                      this.clearRoadSyntaxNodeMarkers({ immediate: true });
                      const buildToken = this.roadSyntaxNodeBuildToken + 1;
                      this.roadSyntaxNodeBuildToken = buildToken;
                      this.roadSyntaxNodeBuildRunning = true;
                      const markers = [];
                      let index = 0;
  
                      const step = () => {
                          if (buildToken !== this.roadSyntaxNodeBuildToken) {
                              this.roadSyntaxEnqueueMapWrite(() => {
                                  markers.forEach((marker) => this.safeMapSet(marker, null));
                                  return { ok: true, marker_count: markers.length };
                              }, {
                                  key: `road_syntax_node_build_abort:${buildToken}`,
                                  replaceExisting: false,
                                  meta: {
                                      reason: 'road_syntax_node_build_abort',
                                      marker_count: markers.length
                                  }
                              });
                              return;
                          }
                          if (!this.shouldRenderRoadSyntaxConnectivityNodes()) {
                              this.roadSyntaxEnqueueMapWrite(() => {
                                  markers.forEach((marker) => this.safeMapSet(marker, null));
                                  return { ok: true, marker_count: markers.length };
                              }, {
                                  key: `road_syntax_node_build_hidden:${buildToken}`,
                                  replaceExisting: false,
                                  meta: {
                                      reason: 'road_syntax_node_build_hidden',
                                      marker_count: markers.length
                                  }
                              });
                              this.roadSyntaxNodeBuildRunning = false;
                              return;
                          }
                          const nowFn = (window.performance && typeof window.performance.now === 'function')
                              ? () => window.performance.now()
                              : () => Date.now();
                          const frameStart = nowFn();
                          const budgetMs = this.roadSyntaxResolveFrameBudget('node');
                          const chunkMarkers = [];
                          while (index < sampledNodes.length) {
                              const feature = sampledNodes[index] || {};
                              index += 1;
                              const loc = this.normalizeLngLat((((feature || {}).geometry || {}).coordinates || []), 'road_syntax.node_marker.center');
                              if (!loc) continue;
                              const props = (feature && feature.properties) || {};
                              const score = this.clamp01(Number(props.degree_score));
                              const marker = new AMap.CircleMarker({
                                  center: loc,
                                  radius: 3 + score * 7,
                                  strokeColor: '#ffffff',
                                  strokeWeight: 1,
                                  fillColor: this.blendTwoColor([203, 213, 225], [153, 27, 27], score),
                                  fillOpacity: 0.88,
                                  zIndex: 115,
                                  bubble: true,
                                  clickable: false,
                                  cursor: 'default',
                              });
                              markers.push(marker);
                              chunkMarkers.push(marker);
                              if ((nowFn() - frameStart) >= budgetMs) break;
                          }
                          if (chunkMarkers.length) {
                              const chunkMarkerCount = chunkMarkers.length;
                              const chunkEndIndex = index;
                              this.roadSyntaxEnqueueMapWrite(() => {
                                  if (buildToken !== this.roadSyntaxNodeBuildToken) {
                                      chunkMarkers.forEach((marker) => this.safeMapSet(marker, null));
                                      return { ok: false, skipped: true, reason: 'stale_node_build_chunk' };
                                  }
                                  const targetMap = (this.mapCore && this.mapCore.map && this.shouldRenderRoadSyntaxConnectivityNodes())
                                      ? this.mapCore.map
                                      : null;
                                  chunkMarkers.forEach((marker) => this.safeMapSet(marker, targetMap));
                                  return {
                                      ok: true,
                                      marker_count: chunkMarkerCount,
                                      visible: !!targetMap
                                  };
                              }, {
                                  key: `road_syntax_node_build_chunk:${buildToken}:${chunkEndIndex}`,
                                  replaceExisting: false,
                                  meta: {
                                      reason: 'road_syntax_node_build_chunk',
                                      marker_count: chunkMarkerCount
                                  }
                              });
                          }
                          this.roadSyntaxNodeMarkers = markers;
                          if (index < sampledNodes.length) {
                              window.requestAnimationFrame(step);
                              return;
                          }
                          this.roadSyntaxNodeBuildRunning = false;
                          this.roadSyntaxNodeSourceFingerprint = sourceFingerprint;
                          this.setRoadSyntaxNodeMarkersVisible(true);
                      };
                      window.requestAnimationFrame(step);
                  },
                  renderRoadSyntaxScatterChart() {
                      if (this.roadSyntaxMainTab !== 'intelligibility') {
                          this.disposeRoadSyntaxScatterChart();
                          return false;
                      }
                      if (!window.echarts) {
                          this.roadSyntaxSetStatus('可理解度图表库未加载（echarts）');
                          return false;
                      }
                      const el = document.getElementById('roadSyntaxScatterChart');
                      if (!el) return false;
                      if (el.clientWidth === 0 || el.clientHeight === 0) return false;
                      const diagnostics = this.roadSyntaxDiagnostics || {};
                      let points = this.normalizeRoadSyntaxScatterPoints(diagnostics.intelligibility_scatter);
                      if (!points.length && Array.isArray(this.roadSyntaxScatterPointsCache) && this.roadSyntaxScatterPointsCache.length) {
                          points = this.normalizeRoadSyntaxScatterPoints(this.roadSyntaxScatterPointsCache);
                      }
                      if (!points.length) {
                          points = this.buildRoadSyntaxScatterFallbackPoints();
                      }
                      if (points.length) {
                          this.roadSyntaxScatterPointsCache = points.slice();
                      }
                      if (!points.length) {
                          this.roadSyntaxSetStatus('可理解度样本为空（暂无可回归数据）');
                          let emptyChart = this.roadSyntaxScatterChart;
                          if (!emptyChart || emptyChart.isDisposed()) {
                              emptyChart = echarts.getInstanceByDom(el) || echarts.init(el);
                              this.roadSyntaxScatterChart = emptyChart;
                          }
                          emptyChart.setOption({
                              animation: false,
                              xAxis: { show: false, min: 0, max: 1 },
                              yAxis: { show: false, min: 0, max: 1 },
                              series: [],
                              graphic: [{
                                  type: 'text',
                                  left: 'center',
                                  top: 'middle',
                                  style: {
                                      text: '暂无可理解度样本点',
                                      fill: '#6b7280',
                                      fontSize: 13
                                  }
                              }]
                          }, true);
                          emptyChart.resize();
                          return true;
                      }
                      let chart = this.roadSyntaxScatterChart;
                      if (!chart || chart.isDisposed()) {
                          chart = echarts.getInstanceByDom(el) || echarts.init(el);
                          this.roadSyntaxScatterChart = chart;
                      }
                      const rv = this.roadSyntaxRegressionView();
                      const xMin = Math.min(...points.map((p) => p[0]));
                      const xMax = Math.max(...points.map((p) => p[0]));
                      const lineData = Number.isFinite(rv.slope) && Number.isFinite(rv.intercept)
                          ? [
                              [xMin, rv.slope * xMin + rv.intercept],
                              [xMax, rv.slope * xMax + rv.intercept],
                          ]
                          : [];
                      try {
                          chart.setOption({
                              animation: false,
                              grid: { left: 42, right: 16, top: 20, bottom: 34 },
                              xAxis: { type: 'value', name: '连接度', nameLocation: 'middle', nameGap: 26, splitLine: { lineStyle: { color: '#eef2f7' } } },
                              yAxis: { type: 'value', name: '整合度', nameGap: 14, splitLine: { lineStyle: { color: '#eef2f7' } } },
                              series: [
                                  {
                                      type: 'scatter',
                                      data: points,
                                      symbolSize: 6,
                                      z: 3,
                                      itemStyle: {
                                          color: '#2563eb',
                                          opacity: 0.82,
                                          borderColor: '#ffffff',
                                          borderWidth: 0.8,
                                      },
                                      emphasis: { scale: false },
                                  },
                                  {
                                      type: 'line',
                                      data: lineData,
                                      showSymbol: false,
                                      z: 2,
                                      lineStyle: { width: 2, color: '#dc2626', opacity: lineData.length ? 0.9 : 0 },
                                  },
                              ],
                              graphic: [],
                          }, true);
                      } catch (err) {
                          console.warn('[road-syntax] scatter setOption failed, retry with simplified series', err);
                          chart.clear();
                          chart.setOption({
                              animation: false,
                              grid: { left: 42, right: 16, top: 20, bottom: 34 },
                              xAxis: { type: 'value', name: '连接度', nameLocation: 'middle', nameGap: 26 },
                              yAxis: { type: 'value', name: '整合度', nameGap: 14 },
                              series: [{
                                  type: 'scatter',
                                  data: points,
                                  symbolSize: 6,
                                  itemStyle: { color: '#2563eb', opacity: 0.85 },
                                  emphasis: { scale: false },
                              }],
                              graphic: [],
                          }, true);
                      }
                      chart.resize();
                      if (String(this.roadSyntaxStatus || '').indexOf('可理解度样本为空') >= 0) {
                          this.roadSyntaxSetStatus('');
                      }
                      return true;
                  },
                  normalizeRoadSyntaxScatterPoints(rawPoints) {
                      const list = Array.isArray(rawPoints) ? rawPoints : [];
                      const out = [];
                      list.forEach((row) => {
                          let x = NaN;
                          let y = NaN;
                          if (Array.isArray(row)) {
                              x = Number(row[0]);
                              y = Number(row[1]);
                          } else if (row && typeof row === 'object') {
                              x = Number(row.x);
                              if (!Number.isFinite(x)) x = Number(row.connectivity_score ?? row.connectivity ?? row.degree_score ?? row.degree);
                              y = Number(row.y);
                              if (!Number.isFinite(y)) y = Number(row.integration_global ?? row.integration_score ?? row.integration);
                          }
                          if (Number.isFinite(x) && Number.isFinite(y)) {
                              out.push([x, y]);
                          }
                      });
                      if (out.length > 8000) {
                          const stride = Math.max(1, Math.ceil(out.length / 8000));
                          return out.filter((_, idx) => idx % stride === 0);
                      }
                      return out;
                  },
                  buildRoadSyntaxScatterFallbackPoints() {
                      let points = [];
                      const nodes = Array.isArray(this.roadSyntaxNodes) ? this.roadSyntaxNodes : [];
                      if (nodes.length) {
                          points = nodes.map((f) => {
                              const props = (f && f.properties) || {};
                              const x = Number.isFinite(Number(props.degree_score))
                                  ? Number(props.degree_score)
                                  : Number(props.degree);
                              return [x, Number(props.integration_global)];
                          }).filter((p) => Number.isFinite(p[0]) && Number.isFinite(p[1]));
                      }
                      if (!points.length) {
                          const roads = Array.isArray(this.roadSyntaxRoadFeatures) ? this.roadSyntaxRoadFeatures : [];
                          points = roads.map((f) => {
                              const props = (f && f.properties) || {};
                              return [Number(props.connectivity_score), Number(props.integration_global)];
                          }).filter((p) => Number.isFinite(p[0]) && Number.isFinite(p[1]));
                      }
                      if (points.length > 8000) {
                          const stride = Math.max(1, Math.ceil(points.length / 8000));
                          points = points.filter((_, idx) => idx % stride === 0);
                      }
                      return points;
                  },
                  buildRoadSyntaxRenderItems(features) {
                      const out = [];
                      let invalidCount = 0;
                      const invalidSamples = [];
                      (Array.isArray(features) ? features : []).forEach((feature, idx) => {
                          const coords = this.normalizePath((((feature || {}).geometry || {}).coordinates || []), 2, 'road_syntax.render_items.path');
                          if (!coords.length) {
                              invalidCount += 1;
                              if (invalidSamples.length < 5) {
                                  const props = ((feature || {}).properties || {});
                                  invalidSamples.push({
                                      idx: idx,
                                      id: props.edge_id || props.id || '',
                                      name: props.name || ''
                                  });
                              }
                              return;
                          }
                          out.push({
                              coords: coords,
                              boundsRect: this.buildRoadSyntaxBoundsRect(coords),
                              props: ((feature || {}).properties || {}),
                          });
                      });
                      if (invalidCount > 0) {
                          console.warn('[road-syntax] skipped invalid road geometries', {
                              invalid_count: invalidCount,
                              total_features: Array.isArray(features) ? features.length : 0,
                              samples: invalidSamples
                          });
                      }
                      return out;
                  },
                  buildRoadSyntaxRenderFingerprint(items) {
                      const list = Array.isArray(items) ? items : [];
                      if (!list.length) return '0';
                      const first = list[0] || {};
                      const last = list[list.length - 1] || {};
                      const firstPt = this.normalizeLngLat((first.coords || [])[0], 'road_syntax.render_fingerprint.first') || [0, 0];
                      const lastCoords = last.coords || [];
                      const lastPt = this.normalizeLngLat(lastCoords[lastCoords.length - 1], 'road_syntax.render_fingerprint.last') || [0, 0];
                      return `${list.length}|${firstPt[0].toFixed(6)},${firstPt[1].toFixed(6)}|${lastPt[0].toFixed(6)},${lastPt[1].toFixed(6)}`;
                  },
                  rebuildRoadSyntaxBasePolylines() {
                      this.roadSyntaxPolylines = [];
                      this.roadSyntaxLayerLodIndexCache = {};
                      this.roadSyntaxTargetVisibleLineSet = {};
                      this.roadSyntaxAppliedVisibleLineSet = {};
                      this.roadSyntaxResetVisibleIndexCache();
                      this.roadSyntaxResetLodScoreCache();
                      this.roadSyntaxResetSpatialIndex();
                      return [];
                  },
                  isRoadSyntaxLayerReady(layerKey) {
                      if (this.roadSyntaxStrictWebglOnly) {
                          return !!(
                              this.roadSyntaxUseArcgisWebgl
                              && typeof this.roadSyntaxCanUseArcgisWebglPayload === 'function'
                              && this.roadSyntaxCanUseArcgisWebglPayload(this.roadSyntaxWebglPayload)
                          );
                      }
                      if (
                          this.roadSyntaxUseArcgisWebgl
                          && typeof this.roadSyntaxCanUseArcgisWebglPayload === 'function'
                          && this.roadSyntaxCanUseArcgisWebglPayload(this.roadSyntaxWebglPayload)
                      ) {
                          return true;
                      }
                      const state = this.roadSyntaxLayerBuildState || {};
                      const styleCache = this.roadSyntaxLayerStyleCache || {};
                      return !!styleCache[layerKey] && state[layerKey] === 'ready';
                  },
                  enqueueRoadSyntaxLayerBuild(layerKey, options = {}) {
                      if (this.roadSyntaxStrictWebglOnly) return;
                      if (!this.roadSyntaxMap() || !window.AMap) return;
                      if (!Array.isArray(this.roadSyntaxPolylineItems) || !this.roadSyntaxPolylineItems.length) return;
                      const priority = !!(options && options.priority);
                      const switchOnReady = !!(options && options.switchOnReady);
                      const state = Object.assign({}, this.roadSyntaxLayerBuildState || {});
                      const queue = Array.isArray(this.roadSyntaxLayerBuildQueue) ? this.roadSyntaxLayerBuildQueue.slice() : [];
                      const cur = state[layerKey];
  
                      if (cur === 'ready') {
                          if (switchOnReady) {
                              this.roadSyntaxPendingLayerKey = layerKey;
                              this.switchRoadSyntaxLayerByKey(layerKey);
                          }
                          return;
                      }
                      if (cur === 'building' || cur === 'queued') {
                          if (switchOnReady) {
                              this.roadSyntaxPendingLayerKey = layerKey;
                          }
                          return;
                      }
  
                      state[layerKey] = 'queued';
                      if (priority) {
                          queue.unshift(layerKey);
                      } else {
                          queue.push(layerKey);
                      }
                      if (switchOnReady) {
                          this.roadSyntaxPendingLayerKey = layerKey;
                      }
                      this.roadSyntaxLayerBuildState = state;
                      this.roadSyntaxLayerBuildQueue = queue;
                      this.scheduleRoadSyntaxLayerBuilder();
                  },
                  scheduleRoadSyntaxLayerBuilder() {
                      if (this.roadSyntaxLayerBuildRunning) return;
                      const queue = Array.isArray(this.roadSyntaxLayerBuildQueue) ? this.roadSyntaxLayerBuildQueue : [];
                      if (!queue.length) return;
                      const layerKey = queue.shift();
                      this.roadSyntaxLayerBuildQueue = queue;
                      const state = Object.assign({}, this.roadSyntaxLayerBuildState || {});
                      state[layerKey] = 'building';
                      this.roadSyntaxLayerBuildState = state;
                      this.roadSyntaxLayerBuildRunning = true;
                      const buildToken = this.roadSyntaxLayerBuildToken + 1;
                      this.roadSyntaxLayerBuildToken = buildToken;
  
                      const parsed = this.parseRoadSyntaxLayerKey(layerKey);
                      const metric = parsed.metric;
                      const metricField = this.resolveRoadSyntaxMetricField(metric, parsed.radiusLabel);
                      const fallbackField = this.resolveRoadSyntaxFallbackField(metric);
                      const items = Array.isArray(this.roadSyntaxPolylineItems) ? this.roadSyntaxPolylineItems : [];
                      const styles = [];
  
                      let index = 0;
                      const step = () => {
                          if (buildToken !== this.roadSyntaxLayerBuildToken) return;
                          if (this.roadSyntaxIsInteractingInMetricView()) {
                              window.setTimeout(() => {
                                  if (buildToken !== this.roadSyntaxLayerBuildToken) return;
                                  window.requestAnimationFrame(step);
                              }, 60);
                              return;
                          }
                          const nowFn = (window.performance && typeof window.performance.now === 'function')
                              ? () => window.performance.now()
                              : () => Date.now();
                          const frameStart = nowFn();
                          const budgetMs = this.roadSyntaxResolveFrameBudget('layer');
                          while (index < items.length) {
                              const item = items[index] || {};
                              index += 1;
                              const style = this.buildRoadSyntaxStyleForMetric(
                                  (item && item.props) || {},
                                  metricField,
                                  fallbackField,
                                  metric,
                                  parsed.skeletonOnly
                              );
                              styles.push(style);
                              if ((nowFn() - frameStart) >= budgetMs) {
                                  break;
                              }
                          }
                          if (index < items.length) {
                              window.requestAnimationFrame(step);
                              return;
                          }
                          const styleCache = Object.assign({}, this.roadSyntaxLayerStyleCache || {});
                          styleCache[layerKey] = styles;
                          this.roadSyntaxLayerStyleCache = styleCache;
                          const map = this.roadSyntaxMap();
                          const pool = Object.assign({}, this.roadSyntaxLayerPool || {});
                          if (pool[layerKey]) {
                              this.roadSyntaxDisposeLayerEntry(pool[layerKey], map);
                          }
                          const fullLayer = this.roadSyntaxBuildLayerFromStyles(layerKey, styles, {
                              variant: 'full',
                          });
                          const lodIndexSet = this.roadSyntaxBuildLayerLodIndexSet(layerKey);
                          const lodLayer = this.roadSyntaxBuildLayerFromStyles(layerKey, styles, {
                              variant: 'lod',
                              includeIndexSet: lodIndexSet,
                              zIndexBoost: 3,
                          });
                          fullLayer.lodLayer = lodLayer;
                          fullLayer.lodIndexSet = this.roadSyntaxCloneIndexSet(lodLayer.indexSet || lodIndexSet);
                          pool[layerKey] = fullLayer;
                          this.roadSyntaxLayerPool = pool;
                          const doneState = Object.assign({}, this.roadSyntaxLayerBuildState || {});
                          doneState[layerKey] = 'ready';
                          this.roadSyntaxLayerBuildState = doneState;
                          this.roadSyntaxLayerBuildRunning = false;
                          const readyMap = this.refreshRoadSyntaxLayerReadyMap();
                          const readyCount = Object.values(readyMap).filter((v) => !!v).length;
                          const totalCount = Object.keys(readyMap).length;
                          if (totalCount > 0 && readyCount >= totalCount) {
                              const hadDegraded = !!this.roadSyntaxPoolDegraded;
                              this.roadSyntaxPoolReady = true;
                              this.roadSyntaxPoolDegraded = false;
                              if (this.roadSyntaxPoolInitRunning) {
                                  this.roadSyntaxPoolInitRunning = false;
                              }
                              if (hadDegraded && this.roadSyntaxUseLegacyPoolStatus()) {
                                  this.roadSyntaxSetStatus(this.roadSyntaxFormatReadyStatus('图层补建完成', readyCount, totalCount));
                              }
                          } else if (this.roadSyntaxPoolInitRunning && this.roadSyntaxUseLegacyPoolStatus()) {
                              this.roadSyntaxSetStatus(this.roadSyntaxFormatReadyStatus('图层预加载中', readyCount, totalCount));
                          }
                          if (this.roadSyntaxPendingLayerKey === layerKey) {
                              this.switchRoadSyntaxLayerByKey(layerKey, { force: true });
                          }
                          this.scheduleRoadSyntaxLayerBuilder();
                      };
                      window.requestAnimationFrame(step);
                  },
                  switchRoadSyntaxLayerByKey(layerKey, options = {}) {
                      const map = this.roadSyntaxMap();
                      if (!map) return;
                      const trackPerf = !options || options.trackPerf !== false;
                      const startAt = this.roadSyntaxNow();
                      if (!this.roadSyntaxUseArcgisWebgl) {
                          this.roadSyntaxSetStatus('ArcGIS-WebGL 未启用，旧版回退已禁用');
                          return;
                      }
                      if (
                          this.roadSyntaxUseArcgisWebgl
                          && typeof this.roadSyntaxCanUseArcgisWebglPayload === 'function'
                          && this.roadSyntaxCanUseArcgisWebglPayload(this.roadSyntaxWebglPayload)
                      ) {
                          this.roadSyntaxActiveLayerKey = String(layerKey || this.resolveRoadSyntaxLayerKey(this.resolveRoadSyntaxActiveMetric()));
                          this.roadSyntaxActiveLayerVariant = 'full';
                          this.roadSyntaxPendingLayerKey = '';
                          this.roadSyntaxDisplaySuspended = false;
                          if (typeof this.renderRoadSyntaxArcgisWebgl === 'function') {
                              this.renderRoadSyntaxArcgisWebgl(this.roadSyntaxWebglPayload, {
                                  hideWhenSuspended: true,
                              }).then((ok) => {
                                  if (ok) {
                                      if (trackPerf) {
                                          this.recordRoadSyntaxSwitchDuration(startAt, layerKey, 0, 0, 'arcgis_webgl');
                                      }
                                  } else if (this.roadSyntaxStrictWebglOnly) {
                                      this.roadSyntaxSetStatus('ArcGIS-WebGL 切换失败（已禁用旧版回退）');
                                  }
                              }).catch((err) => {
                                  console.warn('[road-syntax] arcgis webgl switch render failed', err);
                                  if (this.roadSyntaxStrictWebglOnly) {
                                      this.roadSyntaxSetStatus('ArcGIS-WebGL 切换失败（已禁用旧版回退）');
                                  }
                              });
                          } else if (this.roadSyntaxStrictWebglOnly) {
                              this.roadSyntaxSetStatus('ArcGIS-WebGL 渲染器不可用（已禁用旧版回退）');
                          }
                          return;
                      }
                      this.roadSyntaxSetStatus(this.buildRoadSyntaxWebglUnavailableMessage(this.roadSyntaxWebglPayload));
                  },
                  warmRoadSyntaxLayerPool(activeLayerKey = '') {
                      const state = this.roadSyntaxLayerBuildState || {};
                      const keys = this.roadSyntaxLayerKeysForPrebuild().filter((key) => {
                          if (key === activeLayerKey) return false;
                          const s = state[key];
                          return s !== 'ready' && s !== 'building' && s !== 'queued';
                      });
                      keys.forEach((key) => this.enqueueRoadSyntaxLayerBuild(key, { priority: false, switchOnReady: false }));
                  },
                  waitRoadSyntaxLayerReady(layerKey, timeoutMs = ROAD_SYNTAX_CONST.PREBUILD_DEADLINE_MS) {
                      return new Promise((resolve) => {
                          const start = Date.now();
                          const tick = () => {
                              if (this.isRoadSyntaxLayerReady(layerKey)) {
                                  resolve(true);
                                  return;
                              }
                              if ((Date.now() - start) > timeoutMs) {
                                  resolve(false);
                                  return;
                              }
                              window.setTimeout(tick, 25);
                          };
                          tick();
                      });
                  },
                  prewarmRoadSyntaxLayerVisibility(requestToken, activeLayerKey = '') {
                      if (requestToken !== this.roadSyntaxRequestToken) return Promise.resolve(false);
                      return Promise.resolve(true);
                  },
                  prewarmRoadSyntaxSwitchPath(requestToken, activeLayerKey = '') {
                      return Promise.resolve(requestToken === this.roadSyntaxRequestToken);
                  },
                  async initializeRoadSyntaxPoolFully(requestToken, activeLayerKey = '') {
                      if (this.roadSyntaxStrictWebglOnly) {
                          this.roadSyntaxPoolInitRunning = false;
                          this.roadSyntaxPoolReady = true;
                          this.roadSyntaxPoolDegraded = false;
                          this.roadSyntaxPoolInitTotal = 1;
                          this.roadSyntaxPoolInitDone = 1;
                          return true;
                      }
                      const keysRaw = this.roadSyntaxLayerKeysForPrebuild();
                      const keys = activeLayerKey
                          ? [activeLayerKey].concat(keysRaw.filter((key) => key !== activeLayerKey))
                          : keysRaw.slice();
                      if (!keys.length) {
                          this.roadSyntaxPoolReady = true;
                          this.roadSyntaxPoolDegraded = false;
                          return true;
                      }
                      const totalBudgetMs = Number(this.roadSyntaxPrebuildDeadlineMs || ROAD_SYNTAX_CONST.PREBUILD_DEADLINE_MS);
                      const startedAt = Date.now();
                      this.roadSyntaxPoolInitRunning = true;
                      this.roadSyntaxPoolReady = false;
                      this.roadSyntaxPoolDegraded = false;
                      this.roadSyntaxPoolInitTotal = keys.length;
                      this.roadSyntaxPoolInitDone = 0;
                      if (this.roadSyntaxUseLegacyPoolStatus()) {
                          this.roadSyntaxSetStatus(this.roadSyntaxFormatReadyStatus('图层预加载中', 0, keys.length));
                      }
                      this.refreshRoadSyntaxLayerReadyMap();
                      keys.forEach((key, idx) => this.enqueueRoadSyntaxLayerBuild(key, {
                          priority: idx === 0,
                          switchOnReady: false,
                      }));
  
                      let partial = false;
                      for (let i = 0; i < keys.length; i += 1) {
                          if (requestToken !== this.roadSyntaxRequestToken) {
                              this.roadSyntaxPoolInitRunning = false;
                              return false;
                          }
                          const elapsed = Date.now() - startedAt;
                          const remaining = totalBudgetMs - elapsed;
                          if (remaining <= 0) {
                              partial = true;
                              break;
                          }
                          const ok = await this.waitRoadSyntaxLayerReady(keys[i], remaining);
                          if (!ok) {
                              partial = true;
                              break;
                          }
                          this.roadSyntaxPoolInitDone = i + 1;
                          if (this.roadSyntaxUseLegacyPoolStatus()) {
                              this.roadSyntaxSetStatus(this.roadSyntaxFormatReadyStatus('图层预加载中', this.roadSyntaxPoolInitDone, this.roadSyntaxPoolInitTotal));
                          }
                      }
                      this.roadSyntaxPoolInitRunning = false;
                      const readyMap = this.refreshRoadSyntaxLayerReadyMap();
                      const readyCount = Object.values(readyMap).filter((v) => !!v).length;
                      const allReady = readyCount >= keys.length;
                      this.roadSyntaxPoolReady = allReady;
                      this.roadSyntaxPoolDegraded = !allReady;
                      if (allReady) {
                          if (this.roadSyntaxUseLegacyPoolStatus()) {
                              this.roadSyntaxSetStatus(this.roadSyntaxFormatReadyStatus('图层预加载完成', readyCount, keys.length));
                          }
                          if (this.roadSyntaxEnableHeavyPrewarm) {
                              const prewarmToken = this.roadSyntaxPrewarmToken + 1;
                              this.roadSyntaxPrewarmToken = prewarmToken;
                              window.setTimeout(async () => {
                                  if (prewarmToken !== this.roadSyntaxPrewarmToken) return;
                                  if (requestToken !== this.roadSyntaxRequestToken) return;
                                  try {
                                      await this.prewarmRoadSyntaxLayerVisibility(requestToken, activeLayerKey || keys[0] || '');
                                      await this.prewarmRoadSyntaxSwitchPath(requestToken, activeLayerKey || keys[0] || '');
                                  } catch (_) { }
                              }, 0);
                          }
                      }
                      if (!allReady && partial) {
                          if (this.roadSyntaxUseLegacyPoolStatus()) {
                              this.roadSyntaxSetStatus(`图层预加载超时，进入降级模式：${readyCount}/${keys.length}`);
                          }
                      }
                      return allReady;
                  },
                  renderRoadSyntaxOverlays(roadsFeatureCollection, options = {}) {
                      if (this.roadSyntaxStrictWebglOnly) {
                          this.roadSyntaxSetStatus('ArcGIS-WebGL 模式已启用，旧版图层渲染已禁用');
                          return;
                      }
                      if (!this.roadSyntaxMap() || !window.AMap) return;
                      if (typeof this.clearRoadSyntaxArcgisWebgl === 'function') {
                          this.clearRoadSyntaxArcgisWebgl({ dispose: false });
                      }
                      const forceRebuild = Boolean(options && options.forceRebuild);
                      const displayActive = !(options && options.displayActive === false);
                      const features = ((roadsFeatureCollection || {}).features || []);
                      this.roadSyntaxRoadFeatures = Array.isArray(features) ? features : [];
                      if (!this.roadSyntaxRoadFeatures.length) {
                          this.clearRoadSyntaxOverlays();
                          return;
                      }
                      const renderItems = this.buildRoadSyntaxRenderItems(this.roadSyntaxRoadFeatures);
                      if (!renderItems.length) {
                          this.clearRoadSyntaxOverlays();
                          return;
                      }
                      const fingerprint = this.buildRoadSyntaxRenderFingerprint(renderItems);
                      const shouldRebuildPool = forceRebuild
                          || !this.roadSyntaxSourceFingerprint
                          || this.roadSyntaxSourceFingerprint !== fingerprint
                          || !Object.keys(this.roadSyntaxLayerPool || {}).length;
                      if (shouldRebuildPool) {
                          this.roadSyntaxPoolWarmToken += 1;
                          this.roadSyntaxLayerBuildToken += 1;
                          this.roadSyntaxLayerSwitchToken += 1;
                          this.clearRoadSyntaxLayerPool();
                          this.roadSyntaxPolylineItems = renderItems;
                          this.roadSyntaxSourceFingerprint = fingerprint;
                          this.roadSyntaxPoolRadiusLabel = String(this.roadSyntaxRadiusLabel || 'global');
                          this.roadSyntaxPoolReady = false;
                          this.roadSyntaxPoolDegraded = false;
                          this.rebuildRoadSyntaxBasePolylines();
                      }
                      this.roadSyntaxResetVisibleIndexCache();
                      this.roadSyntaxResetLodScoreCache();
                      const activeMetric = this.resolveRoadSyntaxActiveMetric();
                      const activeLayerKey = this.resolveRoadSyntaxLayerKey(activeMetric);
                      if (displayActive) {
                          if (this.isRoadSyntaxLayerReady(activeLayerKey)) {
                              const desiredVariant = this.roadSyntaxResolveDesiredLayerVariant();
                              const forceSwitch = this.roadSyntaxDisplaySuspended
                                  || !this.roadSyntaxGetLayer(activeLayerKey);
                              this.switchRoadSyntaxLayerByKey(activeLayerKey, {
                                  force: forceSwitch,
                                  preferVariant: desiredVariant,
                              });
                          } else {
                              this.enqueueRoadSyntaxLayerBuild(activeLayerKey, { priority: true, switchOnReady: true });
                              const counts = this.roadSyntaxLayerReadyCounts();
                              if (this.roadSyntaxUseLegacyPoolStatus()) {
                                  this.roadSyntaxSetStatus(`图层预处理中：${counts.ready}/${counts.total || 0}`);
                              }
                          }
                          this.roadSyntaxLogOverlayHealth('render-road-syntax');
                      }
                      this.warmRoadSyntaxLayerPool(activeLayerKey);
                      this.refreshRoadSyntaxLayerReadyMap();
                      this.roadSyntaxPolylineItems = renderItems;
                  },
                  buildRoadSyntaxRequestPayload(polygon, edgeCap, runId = null) {
                      const activeMetric = this.resolveRoadSyntaxActiveMetric();
                      const metricField = this.resolveRoadSyntaxMetricField(activeMetric, this.roadSyntaxRadiusLabel);
                      const useArcgisWebgl = this.roadSyntaxStrictWebglOnly ? true : !!this.roadSyntaxUseArcgisWebgl;
                      const shouldBypassCap = activeMetric === 'control' || activeMetric === 'depth' || activeMetric === 'connectivity' || activeMetric === 'intelligibility';
                      const localGraphModel = this.normalizeRoadSyntaxGraphModel();
                      return {
                          run_id: runId ? String(runId) : null,
                          polygon: polygon,
                          coord_type: 'gcj02',
                          mode: 'walking',
                          graph_model: localGraphModel,
                          highway_filter: 'all',
                          include_geojson: true,
                          max_edge_features: shouldBypassCap ? null : edgeCap,
                          merge_geojson_edges: true,
                          merge_bucket_step: 0.025,
                          radii_m: [600, 800],
                          tulip_bins: 1024,
                          metric: this.resolveRoadSyntaxRequestMetric(),
                          use_arcgis_webgl: useArcgisWebgl,
                          arcgis_timeout_sec: 120,
                          arcgis_metric_field: metricField,
                      };
                  },
                  roadSyntaxResponseHasReadyWebgl(data) {
                      const payload = (data && data.webgl && typeof data.webgl === 'object')
                          ? data.webgl
                          : null;
                      if (typeof this.roadSyntaxCanUseArcgisWebglPayload !== 'function') return false;
                      return this.roadSyntaxCanUseArcgisWebglPayload(payload);
                  },
                  buildRoadSyntaxWebglUnavailableMessage(data) {
                      const payload = (data && data.webgl && typeof data.webgl === 'object')
                          ? data.webgl
                          : ((data && typeof data === 'object') ? data : null);
                      if (!payload || typeof payload !== 'object') {
                          return 'ArcGIS-WebGL 数据未就绪（已禁用旧版回退）: payload_missing';
                      }
                      const enabled = !!payload.enabled;
                      const status = String((payload && payload.status) || '').trim();
                      const roads = (payload && payload.roads && typeof payload.roads === 'object')
                          ? payload.roads
                          : {};
                      const features = Array.isArray(roads.features) ? roads.features : [];
                      const featureCount = features.length;
                      const countRaw = Number(roads.count);
                      const count = Number.isFinite(countRaw) ? countRaw : features.length;
                      if (!enabled) {
                          return status
                              ? `ArcGIS-WebGL 数据未就绪（已禁用旧版回退）: enabled=false, status=${status}, features=${featureCount}, count=${count}`
                              : `ArcGIS-WebGL 数据未就绪（已禁用旧版回退）: enabled=false, features=${featureCount}, count=${count}`;
                      }
                      if (status && status !== 'ok') {
                          return `ArcGIS-WebGL 数据未就绪（已禁用旧版回退）: ${status}`;
                      }
                      if (featureCount <= 0) {
                          return `ArcGIS-WebGL 数据未就绪（已禁用旧版回退）: features=0, count=${count}`;
                      }
                      if (count <= 0) {
                          return 'ArcGIS-WebGL 数据未就绪（已禁用旧版回退）: roads=0';
                      }
                      return `ArcGIS-WebGL 数据未就绪（已禁用旧版回退）: payload_invalid(status=${status || 'empty'}, features=${featureCount}, count=${count})`;
                  },
                  applyRoadSyntaxResponseData(data, preferredMetricTab = 'connectivity') {
                      this.roadSyntaxRoadFeatures = Array.isArray((data && data.roads && data.roads.features) || [])
                          ? data.roads.features
                          : [];
                      this.roadSyntaxNodes = Array.isArray((data && data.nodes && data.nodes.features) || [])
                          ? data.nodes.features
                          : [];
                      this.roadSyntaxDiagnostics = (data && data.diagnostics) ? data.diagnostics : null;
                      this.roadSyntaxScatterPointsCache = this.normalizeRoadSyntaxScatterPoints(
                          this.roadSyntaxDiagnostics && this.roadSyntaxDiagnostics.intelligibility_scatter
                      );
                      this.roadSyntaxSummary = data && data.summary ? data.summary : null;
                      this.roadSyntaxWebglPayload = (data && data.webgl && typeof data.webgl === 'object')
                          ? data.webgl
                          : null;
                      this.roadSyntaxWebglStatus = String((this.roadSyntaxWebglPayload && this.roadSyntaxWebglPayload.status) || '');
                      this.roadSyntaxWebglRadiusFilterCache = null;
                      this.roadSyntaxSkeletonOnly = false;
                      if (!this.roadSyntaxSummary) return;
                      const validMetrics = this.roadSyntaxMetricTabs().map((item) => item.value);
                      const preferred = validMetrics.includes(preferredMetricTab)
                          ? preferredMetricTab
                          : this.roadSyntaxDefaultMetric();
                      const targetMetric = preferred;
                      this.roadSyntaxMetric = targetMetric;
                      this.roadSyntaxLastMetricTab = targetMetric;
                      const radiusOptions = this.roadSyntaxRadiusOptions();
                      const hasGlobal = radiusOptions.some((opt) => String(opt.value || '') === 'global');
                      this.roadSyntaxRadiusLabel = hasGlobal ? 'global' : String((radiusOptions[0] && radiusOptions[0].value) || 'global');
                  },
                  buildRoadSyntaxCompletionStatus(poolReady) {
                      if (!this.roadSyntaxSummary) return '完成：未返回有效汇总数据';
                      const engine = this.roadSyntaxSummary.analysis_engine || 'depthmapxcli';
                      const base = `完成：${this.roadSyntaxSummary.node_count || 0} 节点，${this.roadSyntaxSummary.edge_count || 0} 边段（${engine}`;
                      const controlValid = Number(this.roadSyntaxSummary.control_valid_count || 0);
                      const depthValid = Number(this.roadSyntaxSummary.depth_valid_count || 0);
                      const controlCol = String(this.roadSyntaxSummary.control_source_column || '');
                      const depthCol = String(this.roadSyntaxSummary.depth_source_column || '');
                      let metricHint = '';
                      if (controlValid <= 0 || depthValid <= 0) {
                          metricHint = `；control=${controlValid}${controlCol ? `(${controlCol})` : ''}, depth=${depthValid}${depthCol ? `(${depthCol})` : ''}`;
                      }
                      const webglPayloadReady = (
                          this.roadSyntaxUseArcgisWebgl
                          && typeof this.roadSyntaxCanUseArcgisWebglPayload === 'function'
                          && this.roadSyntaxCanUseArcgisWebglPayload(this.roadSyntaxWebglPayload)
                      );
                      const webglActive = (typeof this.roadSyntaxIsArcgisWebglActive === 'function')
                          ? this.roadSyntaxIsArcgisWebglActive()
                          : (webglPayloadReady && !!this.roadSyntaxWebglActive);
                      if (
                          webglActive
                      ) {
                          return `${base}，ArcGIS-WebGL 已就绪${metricHint}）`;
                      }
                      if (webglPayloadReady) {
                          return `${base}，ArcGIS 数据已返回，但 WebGL 渲染未激活${metricHint}）`;
                      }
                      return `${base}，ArcGIS-WebGL 未就绪（已禁用旧版回退${metricHint}）`;
                  },
                  async computeRoadSyntax() {
                      if (!this.lastIsochroneGeoJSON || this.isComputingRoadSyntax) return;
                      if (this.roadSyntaxMainTab !== 'params') {
                          this.setRoadSyntaxMainTab('params', { refresh: false, syncMetric: false });
                      }
                      if (this.roadSyntaxStrictWebglOnly) {
                          this.roadSyntaxUseArcgisWebgl = true;
                      }
                      this.isComputingRoadSyntax = true;
                      const graphModelLabel = this.roadSyntaxGraphModelLabel();
                      this.roadSyntaxSetStatus(`正在请求路网并计算路网指标（${graphModelLabel}）...`);
                      const requestToken = this.roadSyntaxRequestToken + 1;
                      this.roadSyntaxRequestToken = requestToken;
                      const runId = this.roadSyntaxCreateRunId();
                      this.roadSyntaxStartProgressTracking(runId, requestToken, `局部任务已启动（${graphModelLabel}），正在准备路网`);
                      const preferredMetricTab = this.roadSyntaxLastMetricTab || this.roadSyntaxMetric || this.roadSyntaxDefaultMetric();
                      this.cancelRoadSyntaxRequest('start_new_compute');
                      const requestAbortController = new AbortController();
                      this.roadSyntaxFetchAbortController = requestAbortController;
  
                      try {
                          const polygon = this.getIsochronePolygonPayload();
                          if (!polygon.length) {
                              throw new Error('等时圈范围无效');
                          }
                          this.invalidateRoadSyntaxCache('recompute-road-syntax', { resetData: false, resetPerf: true });
                          this.roadSyntaxSummary = null;
                          this.roadSyntaxRoadFeatures = [];
                          this.roadSyntaxNodes = [];
                          this.roadSyntaxDiagnostics = null;
                          this.roadSyntaxLegendModel = null;
                          const edgeCap = this.resolveRoadSyntaxEdgeCap();
                          const payload = this.buildRoadSyntaxRequestPayload(polygon, edgeCap, runId);
                          const data = await this.fetchRoadSyntaxApi(payload, { signal: requestAbortController.signal });
                          if (requestToken !== this.roadSyntaxRequestToken) {
                              return;
                          }
                          this.roadSyntaxRadiusLabel = 'global';
                          this.applyRoadSyntaxResponseData(data, preferredMetricTab);
                          const webglPayloadReady = (
                              this.roadSyntaxUseArcgisWebgl
                              && typeof this.roadSyntaxCanUseArcgisWebglPayload === 'function'
                              && this.roadSyntaxCanUseArcgisWebglPayload(this.roadSyntaxWebglPayload)
                          );
                          if (!webglPayloadReady) {
                              throw new Error(this.buildRoadSyntaxWebglUnavailableMessage(data));
                          }
  
                          let webglRendered = false;
                          try {
                              if (typeof this.renderRoadSyntaxArcgisWebgl !== 'function') {
                                  throw new Error('ArcGIS-WebGL 渲染器不可用');
                              }
                              webglRendered = await this.renderRoadSyntaxArcgisWebgl(this.roadSyntaxWebglPayload, {
                                  hideWhenSuspended: true,
                              });
                          } catch (err) {
                              console.warn('[road-syntax] arcgis webgl initial render failed', err);
                              webglRendered = false;
                          }
                          if (!webglRendered) {
                              const webglReason = String(this.roadSyntaxWebglStatus || '').trim();
                              throw new Error(
                                  webglReason
                                      ? `ArcGIS-WebGL 渲染失败（已禁用旧版回退）: ${webglReason}`
                                      : 'ArcGIS-WebGL 渲染失败（已禁用旧版回退）'
                              );
                          }
                          this.roadSyntaxPoolReady = true;
                          this.roadSyntaxPoolDegraded = false;
                          this.roadSyntaxPoolInitRunning = false;
                          this.roadSyntaxPoolInitTotal = 1;
                          this.roadSyntaxPoolInitDone = 1;
  
                          const poolReady = true;
                          if (this.roadSyntaxSummary) {
                              this.setRoadSyntaxMainTab(this.roadSyntaxLastMetricTab || this.roadSyntaxDefaultMetric(), {
                                  refresh: false,
                                  syncMetric: true,
                              });
                              if (this.isRoadSyntaxPanelActive()) {
                                  await this.renderRoadSyntaxByMetric(this.roadSyntaxLastMetricTab || this.roadSyntaxMetric || this.roadSyntaxDefaultMetric());
                              } else if (typeof this.suspendRoadSyntaxDisplay === 'function') {
                                  this.suspendRoadSyntaxDisplay();
                              }
                          }
                          this.roadSyntaxSetStatus(`局部（当前多边形）${this.buildRoadSyntaxCompletionStatus(poolReady)}`);
                          if (typeof this.saveAnalysisHistoryAsync === 'function') {
                              this.saveAnalysisHistoryAsync(
                                  this.getIsochronePolygonPayload(),
                                  typeof this.buildSelectedCategoryBuckets === 'function' ? this.buildSelectedCategoryBuckets() : [],
                                  this.allPoisDetails
                              );
                          }
                          if (typeof this.persistAnalysisArtifactQuietly === 'function') {
                              this.persistAnalysisArtifactQuietly('road_syntax');
                          }
                      } catch (e) {
                          if (requestToken !== this.roadSyntaxRequestToken) {
                              return;
                          }
                          if (e && (e.name === 'AbortError' || String(e.message || '').indexOf('aborted') >= 0)) {
                              this.roadSyntaxSetStatus('已取消旧请求，正在使用最新参数计算...');
                              return;
                          }
                          this.roadSyntaxSummary = null;
                          this.roadSyntaxRoadFeatures = [];
                          this.roadSyntaxNodes = [];
                          this.roadSyntaxDiagnostics = null;
                          this.roadSyntaxWebglPayload = null;
                          this.roadSyntaxWebglStatus = '';
                          console.error(e);
                          const rawMessage = (e && e.message ? e.message : String(e));
                          const overpassTimeout = (
                              typeof rawMessage === 'string'
                              && (
                                  rawMessage.indexOf('Overpass query timeout/error') >= 0
                                  || rawMessage.indexOf('Local Overpass request failed') >= 0
                              )
                          );
                          if (overpassTimeout) {
                              this.roadSyntaxSetStatus('失败: 路网抓取超时（Overpass 忙），请等几秒再试，或缩小等时圈范围后重试。');
                              return;
                          }
                          if (this.normalizeRoadSyntaxGraphModel() === 'axial') {
                              const axialMessage = String(rawMessage || '').trim();
                              if (axialMessage.startsWith('轴线图计算失败')) {
                                  this.roadSyntaxSetStatus(`失败: ${axialMessage}`);
                              } else {
                                  this.roadSyntaxSetStatus(`失败: 轴线图计算失败：${axialMessage || '请改用线段图或缩小范围后重试。'}`);
                              }
                          } else {
                              this.roadSyntaxSetStatus('失败: ' + rawMessage);
                          }
                      } finally {
                          if (this.roadSyntaxFetchAbortController === requestAbortController) {
                              this.roadSyntaxFetchAbortController = null;
                          }
                          this.isComputingRoadSyntax = false;
                          this.roadSyntaxStopProgressTracking();
                      }
                  },
                  renderResult(geojson) {
                      if (!geojson || !geojson.geometry) {
                          this.errorMessage = "未获取到有效数据";
                          return;
                      }
                      this.clearIsochroneDebugState();
                      this.lastIsochroneGeoJSON = geojson;
                      this.applySimplifyConfig();
                  },
              }
          });
          mountAnalysisRuntimeApp({
              app: analysisApp,
              pinia,
              target: '#analysis-app-root',
          });
      
}
