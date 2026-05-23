const API = {
    baseUrl: (typeof CONFIG !== 'undefined' ? CONFIG.API_BASE_URL : window.location.origin) + '/api',
    cache: new Map(),
    pendingRequests: new Map(),
    defaultTimeout: 30000,
    debugMode: true,
    
    log(...args) {
        if (this.debugMode) {
            console.log(`[API]`, ...args);
        }
    },
    
    warn(...args) {
        if (this.debugMode) {
            console.warn(`[API WARN]`, ...args);
        }
    },
    
    error(...args) {
        console.error(`[API ERROR]`, ...args);
    },

    cacheConfig: {
        '/portfolio/summary': 60000,
        '/portfolio/positions': 30000,
        '/stock/list': 300000,
        '/stock/detail': 10000,
        '/market/overview': 5000,
        '/news/trendrader': 60000,
        '/strategies': 120000,
        '/settings': 300000
    },

    getToken() {
        return localStorage.getItem('quantpro_token');
    },

    setToken(token) {
        localStorage.setItem('quantpro_token', token);
    },

    clearToken() {
        localStorage.removeItem('quantpro_token');
    },

    getCacheKey(url, options = {}) {
        const body = options.body ? JSON.stringify(options.body) : '';
        return `${url}:${body}`;
    },

    getCache(url) {
        const cached = this.cache.get(url);
        if (!cached) return null;

        const maxAge = this.cacheConfig[url.split('?')[0].replace(this.baseUrl, '')] || 60000;
        if (Date.now() - cached.time > maxAge) {
            this.cache.delete(url);
            return null;
        }

        return cached.data;
    },

    setCache(url, data) {
        this.cache.set(url, {
            data,
            time: Date.now()
        });
    },

    clearCache(pattern = null) {
        if (pattern) {
            for (const key of this.cache.keys()) {
                if (key.includes(pattern)) {
                    this.cache.delete(key);
                }
            }
        } else {
            this.cache.clear();
        }
    },

    async request(endpoint, options = {}) {
        const url = endpoint.startsWith('http') ? endpoint : this.baseUrl + endpoint;
        const useCache = options.method === 'GET' || !options.method;
        const method = options.method || 'GET';
        
        this.log(`➤ 发起请求: ${method} ${url}`);
        this.log('  选项:', options);
        
        if (useCache) {
            const cached = this.getCache(url);
            if (cached) {
                this.log('✓ 使用缓存数据');
                return cached;
            }

            if (this.pendingRequests.has(url)) {
                this.log('⏳ 等待现有请求完成');
                return this.pendingRequests.get(url);
            }
        }

        const headers = {
            'Content-Type': 'application/json',
            ...options.headers
        };

        const controller = new AbortController();
        const timeout = options.timeout || this.defaultTimeout;
        const timeoutId = setTimeout(() => {
            this.warn(`请求超时 (${timeout}ms): ${url}`);
            controller.abort();
        }, timeout);

        const requestOptions = {
            ...options,
            headers,
            signal: controller.signal
        };

        const startTime = Date.now();
        
        const requestPromise = fetch(url, requestOptions)
            .then(async response => {
                clearTimeout(timeoutId);
                const duration = Date.now() - startTime;
                this.log(`✓ 收到响应 (${duration}ms): ${response.status}`);

                if (response.status === 401) {
                    this.warn('API返回401，但已禁用登录验证');
                }

                try {
                    const data = await response.json();
                    this.log('  响应数据:', data);

                    if (!response.ok) {
                        const errorMsg = data.error || `请求失败: ${response.status}`;
                        this.error(errorMsg);
                        throw new Error(errorMsg);
                    }

                    if (useCache) {
                        this.setCache(url, data);
                        this.log('✓ 已缓存响应');
                    }

                    return data;
                } catch (parseError) {
                    this.error('解析JSON响应失败:', parseError);
                    this.error('原始响应:', response);
                    throw new Error('响应格式错误');
                }
            })
            .catch(error => {
                clearTimeout(timeoutId);
                const duration = Date.now() - startTime;
                this.error(`请求失败 (${duration}ms):`, error);
                
                if (error.name === 'AbortError') {
                    this.error(`请求超时 (${timeout}ms)`);
                    throw new Error(`请求超时 (${timeout}ms)`);
                }
                throw error;
            })
            .finally(() => {
                if (useCache) {
                    this.pendingRequests.delete(url);
                }
            });

        if (useCache) {
            this.pendingRequests.set(url, requestPromise);
        }

        return requestPromise;
    },

    get(endpoint, params = {}) {
        const searchParams = new URLSearchParams();
        Object.entries(params).forEach(([key, value]) => {
            if (value !== undefined && value !== null) {
                searchParams.append(key, value);
            }
        });
        const url = searchParams.toString() ? `${endpoint}?${searchParams}` : endpoint;
        return this.request(url);
    },

    post(endpoint, data = {}) {
        return this.request(endpoint, {
            method: 'POST',
            body: JSON.stringify(data)
        });
    },

    put(endpoint, data = {}) {
        return this.request(endpoint, {
            method: 'PUT',
            body: JSON.stringify(data)
        });
    },

    delete(endpoint) {
        return this.request(endpoint, {
            method: 'DELETE'
        });
    },

    async parallel(requests) {
        const promises = requests.map(req => {
            if (typeof req === 'string') {
                return this.get(req);
            } else if (req.url) {
                return this.request(req.url, req.options || {});
            }
            return Promise.resolve(null);
        });

        return Promise.allSettled(promises).then(results => 
            results.map(r => r.status === 'fulfilled' ? r.value : { error: r.reason?.message || '请求失败' })
        );
    },

    async batch(endpoints) {
        const results = {};
        const responses = await this.parallel(endpoints);
        endpoints.forEach((endpoint, index) => {
            const key = endpoint.split('/').pop().split('?')[0];
            results[key] = responses[index];
        });
        return results;
    },

    stream(endpoint, callbacks, options = {}) {
        const url = endpoint.startsWith('http') ? endpoint : this.baseUrl + endpoint;

        return fetch(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                ...options.headers
            },
            body: JSON.stringify(options.body || {})
        }).then(response => {
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';

            function read() {
                return reader.read().then(({ done, value }) => {
                    if (done) {
                        if (callbacks.onComplete) callbacks.onComplete();
                        return;
                    }

                    buffer += decoder.decode(value, { stream: true });
                    const lines = buffer.split('\n');
                    buffer = lines.pop();

                    lines.forEach(line => {
                        if (line.startsWith('data: ')) {
                            const data = line.slice(6);
                            try {
                                const json = JSON.parse(data);
                                if (callbacks.onData) callbacks.onData(json);
                            } catch {
                                if (callbacks.onData) callbacks.onData(data);
                            }
                        }
                    });

                    return read();
                });
            }

            return read();
        }).catch(error => {
            if (callbacks.onError) callbacks.onError(error);
        });
    }
};

async function safeFetch(url, options = {}) {
    console.log(`[safeFetch] ➤ 发起请求: ${url}`);
    console.log('[safeFetch]  选项:', options);
    
    const config = {
        retries: 3,
        retryDelay: 1000,
        timeout: 15000,
        useCache: true,
        cacheExpiry: 30000,
        fallbackToCache: true,
        ...options
    };
    
    const cacheKey = `fetch_cache_${url}`;
    
    for (let attempt = 0; attempt <= config.retries; attempt++) {
        const attemptNum = attempt + 1;
        console.log(`[safeFetch]  尝试 ${attemptNum}/${config.retries + 1}...`);
        
        try {
            const controller = new AbortController();
            const timeoutId = setTimeout(() => {
                console.warn(`[safeFetch] 请求超时 (${config.timeout}ms): ${url}`);
                controller.abort();
            }, config.timeout);

            const headers = { ...(options.headers || {}) };
            const hasBody = options.body !== undefined && options.body !== null;
            const hasContentType = Object.keys(headers).some(k => k.toLowerCase() === 'content-type');
            if (hasBody && !hasContentType) {
                headers['Content-Type'] = 'application/json';
            }

            const requestOptions = {
                ...options,
                headers,
                signal: controller.signal
            };
            
            const startTime = Date.now();
            const response = await fetch(url, requestOptions);
            const duration = Date.now() - startTime;
            
            clearTimeout(timeoutId);
            
            console.log(`[safeFetch]  ✓ 收到响应 (${duration}ms): ${response.status}`);
            
            if (!response.ok) {
                let errorPayload = null;
                try {
                    errorPayload = await response.json();
                } catch (_) {
                    errorPayload = null;
                }
                const serverError = (errorPayload && (errorPayload.error || errorPayload.message))
                    ? (errorPayload.error || errorPayload.message)
                    : `HTTP ${response.status}`;
                console.warn(`[safeFetch] HTTP错误: ${response.status}`);
                if (attempt < config.retries) {
                    const delay = config.retryDelay * (attempt + 1);
                    console.log(`[safeFetch]  等待 ${delay}ms 后重试...`);
                    await sleep(delay);
                    continue;
                }
                console.error('[safeFetch]  已达到最大重试次数');
                if (config.fallbackToCache) {
                    console.log('[safeFetch]  尝试使用缓存数据');
                    const cached = getCachedData(cacheKey);
                    if (cached) return cached;
                }
                return {
                    success: false,
                    error: serverError,
                    status: response.status,
                    data: errorPayload && errorPayload.data ? errorPayload.data : null
                };
            }
            
            try {
                const data = await response.json();
                console.log('[safeFetch]  ✓ 解析JSON成功:', data);
                
                if (config.useCache && data) {
                    setCacheData(cacheKey, data, config.cacheExpiry);
                    console.log('[safeFetch]  ✓ 已缓存响应');
                }
                
                return data;
            } catch (parseError) {
                console.error('[safeFetch]  解析JSON失败:', parseError);
                throw parseError;
            }
            
        } catch (e) {
            const isLastAttempt = attempt === config.retries;
            const isNetworkError = e.name === 'AbortError' || e.message.includes('network');
            
            console.error(`[safeFetch]  错误 (尝试 ${attemptNum}):`, e.message);
            
            if (!isLastAttempt) {
                const delay = config.retryDelay * (attempt + 1);
                console.log(`[safeFetch]  等待 ${delay}ms 后重试...`);
                await sleep(delay);
                continue;
            }
            
            console.error('[safeFetch]  已达到最大重试次数，请求失败');
            
            if (config.fallbackToCache) {
                console.log('[safeFetch]  尝试使用缓存数据');
                const cached = getCachedData(cacheKey);
                if (cached) {
                    console.log('[safeFetch]  ✓ 使用缓存数据');
                    return cached;
                } else {
                    console.warn('[safeFetch]  无缓存可用');
                }
            }
            
            return null;
        }
    }
}

function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

const fetchCache = new Map();

function setCacheData(key, data, expiry = 30000) {
    fetchCache.set(key, {
        data: data,
        expiry: Date.now() + expiry
    });
}

function getCachedData(key) {
    const cached = fetchCache.get(key);
    if (cached && cached.expiry > Date.now()) {
        return cached.data;
    }
    fetchCache.delete(key);
    return null;
}

const NetworkStatus = {
    isOnline: true,
    connectionQuality: 'good',
    lastCheckTime: 0,
    consecutiveFailures: 0,
    maxFailuresBeforeAlert: 3,
    
    init() {
        this.updateStatus();
        
        window.addEventListener('online', () => {
            this.isOnline = true;
            this.showToast('网络已恢复', 'success');
        });
        
        window.addEventListener('offline', () => {
            this.isOnline = false;
            this.showToast('网络已断开', 'warning');
        });
        
        setInterval(() => this.checkConnection(), 30000);
    },
    
    updateStatus() {
        // 更新网络状态显示
        const statusEl = document.getElementById('network-status');
        if (statusEl) {
            statusEl.className = this.isOnline ? 'status-online' : 'status-offline';
            statusEl.textContent = this.isOnline ? '已连接' : '已断开';
        }
    },
    
    async checkConnection() {
        this.lastCheckTime = Date.now();
        
        try {
            const start = Date.now();
            const healthUrl = (typeof CONFIG !== 'undefined' && CONFIG.API_BASE_URL)
                ? `${CONFIG.API_BASE_URL}/api/health`
                : `${window.location.origin}/api/health`;
            const response = await fetch(healthUrl, { 
                method: 'GET',
                cache: 'no-cache'
            });
            const latency = Date.now() - start;
            
            if (response.ok) {
                this.consecutiveFailures = 0;
                
                if (latency < 500) {
                    this.connectionQuality = 'excellent';
                } else if (latency < 1500) {
                    this.connectionQuality = 'good';
                } else if (latency < 3000) {
                    this.connectionQuality = 'poor';
                } else {
                    this.connectionQuality = 'very-poor';
                }
                
                return { ok: true, latency, quality: this.connectionQuality };
            }
        } catch (e) {
            this.consecutiveFailures++;
            
            if (this.consecutiveFailures >= this.maxFailuresBeforeAlert) {
                this.showToast(`网络不稳定 (连续${this.consecutiveFailures}次失败)`, 'error');
            }
        }
        
        return { ok: false };
    },
    
    showToast(message, type = 'info') {
        if (typeof Utils !== 'undefined' && Utils.showToast) {
            Utils.showToast(message, type);
        } else if (typeof showToast === 'function') {
            showToast(message, type);
        }
    },
    
    getStatus() {
        return {
            isOnline: this.isOnline,
            quality: this.connectionQuality,
            lastCheck: this.lastCheckTime,
            failures: this.consecutiveFailures
        };
    }
};

NetworkStatus.init();

const APIEndpoints = {
    auth: {
        login: (username, password) => API.post('/auth/login', { username, password }),
        logout: () => API.post('/auth/logout'),
        verify: () => API.get('/auth/verify')
    },

    portfolio: {
        summary: () => API.get('/portfolio/summary'),
        positions: () => API.get('/portfolio/positions'),
        history: (days = 30) => API.get('/portfolio/history', { days }),
        trades: () => API.get('/portfolio/trades'),
        trade: (data) => API.post('/portfolio/trade', data)
    },

    stock: {
        list: (params) => API.get('/stock/list', params),
        detail: (code) => API.get(`/stock/detail/${code}`),
        search: (keyword) => API.get('/stock/search', { keyword }),
        realtime: (codes) => API.get('/stock/realtime', { codes: codes.join(',') })
    },

    market: {
        overview: () => API.get('/market/overview'),
        indices: () => API.get('/market/indices'),
        hot: () => API.get('/market/hot')
    },

    news: {
        trendrader: (platform = 'all', limit = 50) => API.get('/news/trendrader', { platform, limit }),
        keywords: () => API.get('/news/trendrader/keywords'),
        stocks: () => API.get('/news/trendrader/stocks'),
        refresh: () => API.post('/news/trendrader/refresh'),
        summary: () => API.post('/news/trendrader/summary')
    },

    strategy: {
        list: () => API.get('/strategies'),
        run: (id, params) => API.post('/strategy/run', { strategy_id: id, params }),
        status: (taskId) => API.get(`/strategy/status/${taskId}`)
    },

    backtest: {
        run: (params) => API.post('/backtest/run', params),
        result: (id) => API.get(`/backtest/result/${id}`),
        history: () => API.get('/backtest/history')
    },

    ai: {
        chat: (message, onChunk) => API.stream('/ai/chat', {
            onData: onChunk,
            onError: (e) => console.error('AI chat error:', e)
        }, { body: { message } }),
        analyze: (code) => API.post('/ai/analyze', { code })
    },

    settings: {
        get: () => API.get('/settings'),
        update: (data) => API.put('/settings', data),
        account: () => API.get('/settings/account'),
        updateAccount: (data) => API.post('/settings/account', data)
    }
};

window.API = API;
window.APIEndpoints = APIEndpoints;
window.safeFetch = safeFetch;
