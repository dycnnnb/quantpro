const Nav = {
    links: [
        { href: 'index.html', text: '首页', icon: '🏠' },
        { href: 'positions.html', text: '持仓', icon: '📊' },
        { href: 'backtest.html', text: '回测', icon: '📈' },
        { href: 'market.html', text: '行情', icon: '📉' },
        { href: 'stocks.html', text: '市场', icon: '💹' },
        { href: 'daily-news.html', text: '每日讯息', icon: '📰' },
        { href: 'ai.html', text: 'AI助手', icon: '🤖' },
        { href: 'history.html', text: '历史', icon: '📋' },
        { href: 'settings.html', text: '设置', icon: '⚙️' }
    ],

    render(activePage) {
        const currentPage = window.location.pathname.split('/').pop() || 'index.html';
        const active = activePage || currentPage;

        const linksHtml = this.links.map(link => {
            const isActive = link.href === active ? ' class="active"' : '';
            return `<a href="${link.href}"${isActive}>${link.text}</a>`;
        }).join('\n    ');

        return `
<nav class="nav">
  <div class="nav-logo">
    <div class="nav-logo-icon">Q</div>
    <span class="nav-logo-text">QuantPro</span>
  </div>
  <div class="nav-links">
    ${linksHtml}
  </div>
</nav>`;
    },

    init(activePage) {
        const navContainer = document.querySelector('nav.nav') || document.body.querySelector('nav');
        if (navContainer) {
            navContainer.outerHTML = this.render(activePage);
        }
    }
};

const Loading = {
    spinner(text = '加载中...') {
        return `
            <div class="loading-state">
                <div class="loading-spinner"></div>
                <div class="loading-text">${text}</div>
            </div>
        `;
    },

    skeleton(type = 'card', count = 1) {
        const skeletons = {
            card: `<div class="skeleton skeleton-card"></div>`,
            row: `<div class="skeleton skeleton-row"></div>`,
            text: `<div class="skeleton skeleton-text"></div>`
        };
        return Array(count).fill(skeletons[type] || skeletons.card).join('');
    },

    show(container, text) {
        const el = typeof container === 'string' ? document.querySelector(container) : container;
        if (el) el.innerHTML = this.spinner(text);
    },

    hide(container, content) {
        const el = typeof container === 'string' ? document.querySelector(container) : container;
        if (el) el.innerHTML = content;
    }
};

const Modal = {
    show(options) {
        const { title, content, onConfirm, onCancel, confirmText = '确定', cancelText = '取消' } = options;

        const existing = document.querySelector('.modal-overlay');
        if (existing) existing.remove();

        const modal = document.createElement('div');
        modal.className = 'modal-overlay';
        modal.innerHTML = `
            <div class="modal">
                <div class="modal-header">
                    <h3 class="modal-title">${title}</h3>
                    <button class="modal-close" onclick="Modal.hide()">&times;</button>
                </div>
                <div class="modal-body">${content}</div>
                <div class="modal-footer">
                    <button class="btn btn-secondary" onclick="Modal.hide()">${cancelText}</button>
                    <button class="btn btn-primary" id="modalConfirm">${confirmText}</button>
                </div>
            </div>
        `;

        document.body.appendChild(modal);

        modal.querySelector('#modalConfirm').onclick = () => {
            if (onConfirm) onConfirm();
            this.hide();
        };

        modal.onclick = (e) => {
            if (e.target === modal) this.hide();
        };

        return modal;
    },

    hide() {
        const modal = document.querySelector('.modal-overlay');
        if (modal) modal.remove();
    },

    alert(message, title = '提示') {
        return this.show({
            title,
            content: `<p>${message}</p>`,
            confirmText: '知道了',
            cancelText: null
        });
    },

    confirm(message, onConfirm, title = '确认') {
        return this.show({
            title,
            content: `<p>${message}</p>`,
            onConfirm
        });
    }
};

document.addEventListener('DOMContentLoaded', () => {
    Nav.init();
});

window.Nav = Nav;
window.Loading = Loading;
window.Modal = Modal;
