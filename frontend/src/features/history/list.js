    function createAnalysisHistoryListInitialState() {
        return {
            historyListRaw: [],
            historyList: [],
            historyLoading: false,
            historyLoadError: '',
            historyLoadedCount: 0,
            historySkeletonCount: 5,
            historyHasLoadedOnce: false,
            historyRenderSessionId: 0,
            historyRenderRafId: null,
            historyFetchAbortController: null,
            isSelectionMode: false,
            selectedHistoryIds: [],
            currentHistoryRecordId: '',
        };
    }

    function createAnalysisHistoryListMethods() {
        return {
            captureHistoryReturnContext() {
                const sidebarView = String(this.sidebarView || '').trim().toLowerCase();
                if (sidebarView === 'wizard') {
                    this.historyReturnContext = {
                        sidebarView: 'wizard',
                        step: Number.isFinite(Number(this.step)) ? Number(this.step) : 1,
                        activeStep3Panel: String(this.activeStep3Panel || '').trim().toLowerCase() || 'poi',
                    };
                    return;
                }
                this.historyReturnContext = {
                    sidebarView: 'start',
                    step: 1,
                    activeStep3Panel: '',
                };
            },
            getHistoryBackButtonLabel() {
                if (this.isSelectionMode) {
                    return '取消';
                }
                const context = this.historyReturnContext || {};
                const sidebarView = String(context.sidebarView || '').trim().toLowerCase();
                const step = Number(context.step || 0);
                if (sidebarView === 'wizard') {
                    return step === 2 ? '← 返回结果界面' : '← 返回分析界面';
                }
                return '← 返回主界面';
            },
            backFromHistory() {
                if (this.isSelectionMode) {
                    this.toggleSelectionMode(false);
                    return;
                }
                const context = this.historyReturnContext || {};
                const sidebarView = String(context.sidebarView || '').trim().toLowerCase();
                if (sidebarView === 'wizard') {
                    this.sidebarView = 'wizard';
                    this.step = Number.isFinite(Number(context.step)) ? Number(context.step) : 1;
                    const panel = String(context.activeStep3Panel || '').trim().toLowerCase();
                    if (this.step === 2 && panel) {
                        if (typeof this.selectStep3Panel === 'function') {
                            this.selectStep3Panel(panel);
                        } else {
                            this.activeStep3Panel = panel;
                        }
                    }
                    this.historyReturnContext = null;
                    return;
                }
                this.historyReturnContext = null;
                if (typeof this.backToHome === 'function') {
                    this.backToHome();
                    return;
                }
                this.sidebarView = 'start';
                this.step = 1;
            },
            cancelHistoryLoading() {
                if (this.historyFetchAbortController) {
                    try {
                        this.historyFetchAbortController.abort();
                    } catch (e) {
                        console.warn('history abort failed', e);
                    }
                    this.historyFetchAbortController = null;
                }
                if (this.historyRenderRafId !== null) {
                    window.cancelAnimationFrame(this.historyRenderRafId);
                    this.historyRenderRafId = null;
                }
                this.historyRenderSessionId += 1;
            },
            normalizePoiSource(source, fallback = 'local') {
                const raw = String(source || '').trim().toLowerCase();
                if (!raw) return fallback;
                if (raw === 'local' || raw === 'history' || raw === 'historical') return 'local';
                if (raw === 'gaode' || raw === 'amap') return 'gaode';
                return fallback;
            },
            getPoiSourceLabel(source, year = null) {
                const normalized = this.normalizePoiSource(source, 'unknown');
                const yearValue = Number.isFinite(Number(year)) ? Number(year) : null;
                if (normalized === 'local') return `本地源（${yearValue || 2020}年）`;
                if (normalized === 'gaode') return `高德源（${yearValue || 2026}年）`;
                return '未标记';
            },
            normalizeHistoryRecord(item) {
                const record = Object.assign({}, item || {});
                const rawDate = record.created_at;
                let dateText = String(rawDate || '');
                if (rawDate) {
                    const rawDateText = String(rawDate).trim();
                    const hasTimezone = /(?:Z|[+-]\d{2}:\d{2})$/i.test(rawDateText);
                    const normalizedDateText = hasTimezone ? rawDateText : `${rawDateText}Z`;
                    const d = new Date(normalizedDateText);
                    if (!Number.isNaN(d.getTime())) {
                        dateText = d.toLocaleDateString();
                    }
                }
                record._createdDateText = dateText;
                const rawSource = record && record.params ? record.params.source : '';
                const normalizedSource = this.normalizePoiSource(rawSource, 'unknown');
                record._source = normalizedSource;
                record._sourceLabel = this.getPoiSourceLabel(normalizedSource, record && record.params ? record.params.year : null);
                return record;
            },
            progressiveRenderHistory(sessionId) {
                if (sessionId !== this.historyRenderSessionId) return;
                if (!Array.isArray(this.historyListRaw)) {
                    this.historyLoading = false;
                    this.historyRenderRafId = null;
                    return;
                }
                if (this.historyLoadedCount >= this.historyListRaw.length) {
                    this.historyLoading = false;
                    this.historyRenderRafId = null;
                    return;
                }

                const nextItem = this.historyListRaw[this.historyLoadedCount];
                this.historyList.push(nextItem);
                this.historyLoadedCount += 1;

                this.historyRenderRafId = window.requestAnimationFrame(() => {
                    this.progressiveRenderHistory(sessionId);
                });
            },
            preloadHistoryListInBackground() {
                if (this.historyHasLoadedOnce || this.historyLoading) {
                    return;
                }
                this.loadHistoryList({ force: true, keepExisting: false, background: true }).catch((err) => {
                    console.warn('History background preload failed', err);
                });
            },
            openHistoryView() {
                this.captureHistoryReturnContext();
                this.sidebarView = 'history';
                this.loadHistoryList({ force: false, keepExisting: true, background: false }).catch((err) => {
                    console.warn('History load failed', err);
                });
            },
            refreshHistoryList() {
                this.loadHistoryList({ force: true, keepExisting: true, hardRefresh: true }).catch((err) => {
                    console.warn('History refresh failed', err);
                });
            },
            async loadHistoryList(options = {}) {
                const force = !!(options && options.force);
                const background = !!(options && options.background);
                const hardRefresh = !!(options && options.hardRefresh);
                const keepExisting = options && Object.prototype.hasOwnProperty.call(options, 'keepExisting')
                    ? !!options.keepExisting
                    : (this.historyHasLoadedOnce && this.historyList.length > 0);
                this.historyLoadError = '';
                if (!force && this.historyHasLoadedOnce) {
                    return;
                }
                if (this.historyLoading && !force) {
                    return;
                }
                this.cancelHistoryLoading();
                const sessionId = this.historyRenderSessionId;
                this.historyLoading = true;
                if (!keepExisting && !background) {
                    this.historyListRaw = [];
                    this.historyList = [];
                    this.historyLoadedCount = 0;
                }
                this.historyFetchAbortController = new AbortController();
                const timerHost = (typeof window !== 'undefined' && typeof window.setTimeout === 'function')
                    ? window
                    : globalThis;
                const historyLoadTimeoutMs = 15000;
                const historyLoadTimeoutId = timerHost.setTimeout(() => {
                    if (sessionId === this.historyRenderSessionId && this.historyFetchAbortController) {
                        this.historyFetchAbortController.abort();
                    }
                }, historyLoadTimeoutMs);

                try {
                    const historyPath = '/api/v1/analysis/history?limit=100';
                    const historyUrl = hardRefresh
                        ? `${historyPath}&_ts=${Date.now()}`
                        : historyPath;
                    const res = await fetch(historyUrl, {
                        signal: this.historyFetchAbortController.signal,
                        cache: hardRefresh ? 'no-store' : 'default'
                    });
                    if (!res.ok) {
                        throw new Error(`历史记录请求失败(${res.status})`);
                    }
                    const data = await res.json();
                    if (sessionId !== this.historyRenderSessionId) return;
                    const normalized = Array.isArray(data)
                        ? data.map((item) => this.normalizeHistoryRecord(item))
                        : [];
                    this.historyListRaw = normalized;
                    this.historyList = normalized.slice();
                    this.historyLoadedCount = normalized.length;
                    this.historyLoading = false;
                    this.historyRenderRafId = null;
                    this.historyHasLoadedOnce = true;
                } catch (e) {
                    if (e && e.name === 'AbortError') {
                        if (sessionId === this.historyRenderSessionId) {
                            console.warn('History load timed out or was cancelled');
                            this.historyLoading = false;
                            this.historyLoadError = '历史记录加载超时，请检查数据库连接后重试';
                        }
                        return;
                    }
                    console.error('History Load Error:', e);
                    if (sessionId !== this.historyRenderSessionId) return;
                    this.historyLoading = false;
                    this.historyLoadError = e && e.message ? e.message : '历史记录加载失败，请检查数据库连接';
                    if (!keepExisting && !background) {
                        this.historyListRaw = [];
                        this.historyList = [];
                        this.historyLoadedCount = 0;
                    }
                } finally {
                    timerHost.clearTimeout(historyLoadTimeoutId);
                    if (sessionId === this.historyRenderSessionId) {
                        this.historyFetchAbortController = null;
                    }
                }
            },
            toggleSelectionMode(active) {
                this.isSelectionMode = active;
                this.selectedHistoryIds = [];
            },
            handleHistoryItemClick(item) {
                if (this.isSelectionMode) {
                    const idx = this.selectedHistoryIds.indexOf(item.id);
                    if (idx > -1) {
                        this.selectedHistoryIds.splice(idx, 1);
                    } else {
                        this.selectedHistoryIds.push(item.id);
                    }
                } else {
                    this.loadHistoryDetail(item.id);
                }
            },
            async deleteSelectedHistory() {
                const count = this.selectedHistoryIds.length;
                if (count === 0) return;

                if (!confirm(`确定要删除选中的 ${count} 条记录吗？`)) return;

                try {
                    const deletePromises = this.selectedHistoryIds.map((id) =>
                        fetch(`/api/v1/analysis/history/${id}`, { method: 'DELETE' })
                    );

                    await Promise.all(deletePromises);

                    const removedIds = new Set(this.selectedHistoryIds);
                    this.historyList = this.historyList.filter((item) => !removedIds.has(item.id));
                    this.historyListRaw = this.historyListRaw.filter((item) => !removedIds.has(item.id));
                    this.historyLoadedCount = this.historyList.length;
                    if (typeof this.loadAgentSessionSummaries === 'function') {
                        this.loadAgentSessionSummaries(true).catch((err) => {
                            console.warn('Agent session summaries refresh failed after history delete', err);
                        });
                    }
                    this.selectedHistoryIds = [];
                    this.isSelectionMode = false;
                } catch (e) {
                    console.error('Batch delete failed', e);
                    alert('批量删除失败');
                }
            },
            async deleteHistory(id) {
                if (!confirm('确定要删除这条记录吗？')) return;
                try {
                    await fetch(`/api/v1/analysis/history/${id}`, { method: 'DELETE' });
                    this.historyList = this.historyList.filter((item) => item.id !== id);
                    this.historyListRaw = this.historyListRaw.filter((item) => item.id !== id);
                    this.historyLoadedCount = this.historyList.length;
                    if (typeof this.loadAgentSessionSummaries === 'function') {
                        this.loadAgentSessionSummaries(true).catch((err) => {
                            console.warn('Agent session summaries refresh failed after history delete', err);
                        });
                    }
                } catch (e) {
                    console.error(e);
                }
            },
        };
    }

export { createAnalysisHistoryListInitialState, createAnalysisHistoryListMethods };
