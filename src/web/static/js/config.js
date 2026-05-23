const runtimeApiBase = (() => {
    const explicit = window.QUANTPRO_API_BASE_URL;
    if (explicit && typeof explicit === 'string') {
        return explicit.replace(/\/$/, '');
    }

    const localDefault = 'http://127.0.0.1:5000';
    const { protocol, hostname } = window.location;
    if (!protocol || !protocol.startsWith('http')) {
        return localDefault;
    }

    if (hostname === '127.0.0.1' || hostname === 'localhost') {
        return localDefault;
    }

    return `${window.location.origin}`;
})();

const CONFIG = {
    API_BASE_URL: runtimeApiBase,
    API_TIMEOUT: 8000,
    AI_API_TIMEOUT: 60000,
    AUTO_LOGIN_LOCAL: true,

    getApiUrl: function(endpoint) {
        return this.API_BASE_URL + endpoint;
    },

    formatDate: function(date) {
        const year = date.getFullYear();
        const month = String(date.getMonth() + 1).padStart(2, '0');
        const day = String(date.getDate()).padStart(2, '0');
        return `${year}-${month}-${day}`;
    },

    formatDateTime: function(date) {
        const year = date.getFullYear();
        const month = String(date.getMonth() + 1).padStart(2, '0');
        const day = String(date.getDate()).padStart(2, '0');
        const hours = String(date.getHours()).padStart(2, '0');
        const minutes = String(date.getMinutes()).padStart(2, '0');
        const seconds = String(date.getSeconds()).padStart(2, '0');
        return `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`;
    },

    formatChineseDate: function(date) {
        const year = date.getFullYear();
        const month = date.getMonth() + 1;
        const day = date.getDate();
        return `${year}年${month}月${day}日`;
    },

    formatMoney: function(amount) {
        if (amount >= 100000000) {
            return (amount / 100000000).toFixed(2) + '亿';
        } else if (amount >= 10000) {
            return (amount / 10000).toFixed(2) + '万';
        }
        return amount.toFixed(2);
    },

    formatPercent: function(value) {
        return (value * 100).toFixed(2) + '%';
    }
};

if (CONFIG.AUTO_LOGIN_LOCAL && !localStorage.getItem('quantpro_token')) {
    fetch(CONFIG.API_BASE_URL + '/api/auth/local-login', { method: 'POST' })
        .then(r => r.ok ? r.json() : null)
        .then(data => {
            if (data && data.success && data.token) {
                localStorage.setItem('quantpro_token', data.token);
                localStorage.setItem('quantpro_user', JSON.stringify(data.user || { username: 'local', name: '本机用户' }));
            }
        })
        .catch(() => {});
}

async function safeFetch(url, options = {}) {
    const timeout = options.timeout || CONFIG.API_TIMEOUT;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeout);
    try {
        const resp = await fetch(url, {
            ...options,
            signal: controller.signal,
            headers: { 'Content-Type': 'application/json', ...options.headers }
        });
        clearTimeout(timer);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        return await resp.json();
    } catch (e) {
        clearTimeout(timer);
        if (e.name === 'AbortError') {
            console.warn(`[API] 请求超时(${timeout}ms): ${url}`);
        } else {
            console.warn(`[API] 请求失败: ${url}`, e.message);
        }
        return null;
    }
}

window.safeFetch = safeFetch;

let _backendAlive = null;
let _backendCheckTime = 0;
async function isBackendAlive() {
    if (_backendAlive !== null && Date.now() - _backendCheckTime < 300000) return _backendAlive;
    try {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), 3000);
        const resp = await fetch(CONFIG.API_BASE_URL + '/api/health', { signal: controller.signal });
        clearTimeout(timer);
        _backendAlive = resp.ok;
    } catch {
        _backendAlive = false;
    }
    _backendCheckTime = Date.now();
    return _backendAlive;
}

(function() {
    const _originalFetch = window.fetch;
    window.fetch = function(url, options = {}) {
        const isApiCall = typeof url === 'string' && url.includes(CONFIG.API_BASE_URL);
        if (isApiCall && !options.signal) {
            const controller = new AbortController();
            const timeout = options.timeout || CONFIG.API_TIMEOUT;
            const timer = setTimeout(() => controller.abort(), timeout);
            options = { ...options, signal: controller.signal };
            return _originalFetch.call(window, url, options).then(resp => {
                clearTimeout(timer);
                return resp;
            }).catch(err => {
                clearTimeout(timer);
                if (err.name === 'AbortError') {
                    console.warn(`[API] 请求超时(${timeout}ms): ${url}`);
                }
                throw err;
            });
        }
        return _originalFetch.call(window, url, options);
    };
})();

function showToast(message, type = 'info') {
    const existing = document.querySelector('.toast-notification');
    if (existing) existing.remove();
    const toast = document.createElement('div');
    toast.className = 'toast-notification';
    const colors = { success: 'var(--green)', error: 'var(--red)', warning: 'var(--orange)', info: 'var(--blue, #3b82f6)' };
    toast.style.cssText = `
        position:fixed;top:20px;right:20px;z-index:10000;
        padding:12px 20px;border-radius:8px;font-size:14px;
        background:${colors[type] || colors.info};color:white;
        box-shadow:0 4px 12px rgba(0,0,0,.3);
        animation:slideIn .3s ease;
    `;
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => { toast.style.opacity = '0'; setTimeout(() => toast.remove(), 300); }, 3000);
}
