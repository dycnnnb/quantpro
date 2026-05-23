const Utils = {
    formatVolume(volume) {
        if (volume >= 100000000) {
            return (volume / 100000000).toFixed(2) + '亿';
        } else if (volume >= 10000) {
            return (volume / 10000).toFixed(2) + '万';
        }
        return volume.toString();
    },

    formatAmount(amount) {
        if (amount >= 100000000) {
            return (amount / 100000000).toFixed(2) + '亿';
        } else if (amount >= 10000) {
            return (amount / 10000).toFixed(2) + '万';
        }
        return amount.toString();
    },

    formatPercent(value, decimals = 2) {
        if (value === null || value === undefined) return '--';
        const sign = value >= 0 ? '+' : '';
        return sign + (value * 100).toFixed(decimals) + '%';
    },

    formatPrice(price, decimals = 2) {
        if (price === null || price === undefined) return '--';
        return Number(price).toFixed(decimals);
    },

    formatDate(date, format = 'YYYY-MM-DD') {
        const d = new Date(date);
        const year = d.getFullYear();
        const month = String(d.getMonth() + 1).padStart(2, '0');
        const day = String(d.getDate()).padStart(2, '0');
        const hours = String(d.getHours()).padStart(2, '0');
        const minutes = String(d.getMinutes()).padStart(2, '0');
        
        return format
            .replace('YYYY', year)
            .replace('MM', month)
            .replace('DD', day)
            .replace('HH', hours)
            .replace('mm', minutes);
    },

    formatTime(date) {
        const d = new Date(date);
        return String(d.getHours()).padStart(2, '0') + ':' + 
               String(d.getMinutes()).padStart(2, '0');
    },

    debounce(fn, delay = 300) {
        let timer = null;
        return function(...args) {
            clearTimeout(timer);
            timer = setTimeout(() => fn.apply(this, args), delay);
        };
    },

    throttle(fn, delay = 100) {
        let last = 0;
        return function(...args) {
            const now = Date.now();
            if (now - last >= delay) {
                last = now;
                fn.apply(this, args);
            }
        };
    },

    getPriceColor(change) {
        if (change > 0) return 'var(--red)';
        if (change < 0) return 'var(--green)';
        return 'var(--text-2)';
    },

    showLoading(container, text = '加载中...') {
        const el = typeof container === 'string' ? document.querySelector(container) : container;
        if (!el) return;
        el.innerHTML = `
            <div class="loading-state">
                <div class="loading-spinner"></div>
                <div class="loading-text">${text}</div>
            </div>
        `;
    },

    showError(container, message = '加载失败') {
        const el = typeof container === 'string' ? document.querySelector(container) : container;
        if (!el) return;
        el.innerHTML = `
            <div class="error-state">
                <div class="error-icon">⚠️</div>
                <div class="error-text">${message}</div>
                <button class="retry-btn" onclick="location.reload()">重试</button>
            </div>
        `;
    },

    showEmpty(container, message = '暂无数据') {
        const el = typeof container === 'string' ? document.querySelector(container) : container;
        if (!el) return;
        el.innerHTML = `
            <div class="empty-state">
                <div class="empty-icon">📭</div>
                <div class="empty-text">${message}</div>
            </div>
        `;
    },

    showToast(message, type = 'info', duration = 3000) {
        const existing = document.querySelector('.toast-notification');
        if (existing) existing.remove();

        const toast = document.createElement('div');
        toast.className = `toast-notification toast-${type}`;
        toast.innerHTML = `
            <span class="toast-icon">${type === 'success' ? '✓' : type === 'error' ? '✗' : 'ℹ'}</span>
            <span class="toast-message">${message}</span>
        `;
        
        toast.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            padding: 12px 20px;
            background: ${type === 'success' ? 'var(--green)' : type === 'error' ? 'var(--red)' : 'var(--text-1)'};
            color: white;
            border-radius: 8px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
            z-index: 10000;
            display: flex;
            align-items: center;
            gap: 8px;
            animation: slideIn 0.3s ease;
        `;

        document.body.appendChild(toast);
        setTimeout(() => {
            toast.style.animation = 'slideOut 0.3s ease';
            setTimeout(() => toast.remove(), 300);
        }, duration);
    },

    initCardEffects() {
        document.querySelectorAll('.card, .stat-card, .news-card, .strategy-card').forEach(card => {
            card.addEventListener('mousemove', (e) => {
                const rect = card.getBoundingClientRect();
                card.style.setProperty('--mx', (e.clientX - rect.left) + 'px');
                card.style.setProperty('--my', (e.clientY - rect.top) + 'px');
            });
        });
    },

    animateNumber(el, target, duration = 1000, decimals = 2) {
        const start = parseFloat(el.textContent) || 0;
        const startTime = performance.now();
        
        function update(currentTime) {
            const elapsed = currentTime - startTime;
            const progress = Math.min(elapsed / duration, 1);
            const easeProgress = 1 - Math.pow(1 - progress, 3);
            const current = start + (target - start) * easeProgress;
            el.textContent = current.toFixed(decimals);
            
            if (progress < 1) {
                requestAnimationFrame(update);
            }
        }
        
        requestAnimationFrame(update);
    },

    copyToClipboard(text) {
        if (navigator.clipboard) {
            navigator.clipboard.writeText(text).then(() => {
                this.showToast('已复制到剪贴板', 'success');
            });
        } else {
            const textarea = document.createElement('textarea');
            textarea.value = text;
            document.body.appendChild(textarea);
            textarea.select();
            document.execCommand('copy');
            document.body.removeChild(textarea);
            this.showToast('已复制到剪贴板', 'success');
        }
    },

    getQueryParams() {
        const params = new URLSearchParams(window.location.search);
        const result = {};
        for (const [key, value] of params) {
            result[key] = value;
        }
        return result;
    },

    sleep(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }
};

const Skeleton = {
    card() {
        return `
            <div class="skeleton-card">
                <div class="skeleton-line skeleton-title"></div>
                <div class="skeleton-line skeleton-text"></div>
                <div class="skeleton-line skeleton-text short"></div>
            </div>
        `;
    },

    list(count = 5) {
        return Array(count).fill(0).map(() => `
            <div class="skeleton-item">
                <div class="skeleton-line skeleton-title"></div>
                <div class="skeleton-line skeleton-text short"></div>
            </div>
        `).join('');
    },

    table(rows = 5, cols = 4) {
        return `
            <div class="skeleton-table">
                ${Array(rows).fill(0).map(() => `
                    <div class="skeleton-row">
                        ${Array(cols).fill(0).map(() => 
                            '<div class="skeleton-cell"></div>'
                        ).join('')}
                    </div>
                `).join('')}
            </div>
        `;
    },

    stat() {
        return `
            <div class="skeleton-stat">
                <div class="skeleton-line skeleton-value"></div>
                <div class="skeleton-line skeleton-label"></div>
            </div>
        `;
    }
};

const AutoRefresh = {
    interval: null,
    callbacks: [],
    defaultInterval: 30000,

    start(intervalMs = this.defaultInterval) {
        if (this.interval) this.stop();
        
        this.interval = setInterval(() => {
            if (document.visibilityState === 'visible') {
                this.callbacks.forEach(cb => cb());
            }
        }, intervalMs);

        document.addEventListener('visibilitychange', this.handleVisibility);
    },

    stop() {
        if (this.interval) {
            clearInterval(this.interval);
            this.interval = null;
        }
        document.removeEventListener('visibilitychange', this.handleVisibility);
    },

    addCallback(callback) {
        this.callbacks.push(callback);
    },

    removeCallback(callback) {
        this.callbacks = this.callbacks.filter(cb => cb !== callback);
    },

    handleVisibility() {
        if (document.visibilityState === 'visible') {
            AutoRefresh.callbacks.forEach(cb => cb());
        }
    }
};

document.addEventListener('DOMContentLoaded', () => {
    Utils.initCardEffects();
});

window.Utils = Utils;
window.Skeleton = Skeleton;
window.AutoRefresh = AutoRefresh;
