const Storage = {
    prefix: 'quantpro_',

    get(key, defaultValue = null) {
        try {
            const data = localStorage.getItem(this.prefix + key);
            return data ? JSON.parse(data) : defaultValue;
        } catch {
            return defaultValue;
        }
    },

    set(key, value) {
        try {
            localStorage.setItem(this.prefix + key, JSON.stringify(value));
            return true;
        } catch (e) {
            console.error('Storage set error:', e);
            return false;
        }
    },

    remove(key) {
        localStorage.removeItem(this.prefix + key);
    },

    clear() {
        Object.keys(localStorage)
            .filter(key => key.startsWith(this.prefix))
            .forEach(key => localStorage.removeItem(key));
    },

    getWithExpiry(key, maxAge = 60000) {
        const data = this.get(key);
        if (!data || !data.timestamp) return null;

        if (Date.now() - data.timestamp > maxAge) {
            this.remove(key);
            return null;
        }

        return data.value;
    },

    setWithExpiry(key, value) {
        this.set(key, {
            value,
            timestamp: Date.now()
        });
    },

    token: {
        get() {
            return Storage.get('token');
        },
        set(token) {
            Storage.set('token', token);
        },
        remove() {
            Storage.remove('token');
        },
        isValid() {
            return !!Storage.get('token');
        }
    },

    user: {
        get() {
            return Storage.get('user');
        },
        set(user) {
            Storage.set('user', user);
        },
        remove() {
            Storage.remove('user');
        }
    },

    watchlist: {
        get() {
            return Storage.get('watchlist', []);
        },
        set(list) {
            Storage.set('watchlist', list);
        },
        add(code) {
            const list = this.get();
            if (!list.includes(code)) {
                list.push(code);
                this.set(list);
            }
        },
        remove(code) {
            const list = this.get().filter(c => c !== code);
            this.set(list);
        },
        has(code) {
            return this.get().includes(code);
        }
    },

    history: {
        get() {
            return Storage.get('history', []);
        },
        add(item) {
            const list = this.get();
            list.unshift({ ...item, timestamp: Date.now() });
            if (list.length > 100) list.pop();
            this.set(list);
        },
        clear() {
            Storage.set('history', []);
        }
    },

    settings: {
        get() {
            return Storage.get('settings', {
                theme: 'light',
                autoRefresh: true,
                refreshInterval: 30000,
                notifications: true
            });
        },
        set(settings) {
            Storage.set('settings', settings);
        },
        update(key, value) {
            const settings = this.get();
            settings[key] = value;
            this.set(settings);
        }
    },

    cache: {
        get(key) {
            return Storage.getWithExpiry(`cache_${key}`, 300000);
        },
        set(key, value) {
            Storage.setWithExpiry(`cache_${key}`, value);
        },
        remove(key) {
            Storage.remove(`cache_${key}`);
        },
        clear() {
            Object.keys(localStorage)
                .filter(key => key.startsWith(this.prefix + 'cache_'))
                .forEach(key => localStorage.removeItem(key));
        }
    }
};

window.Storage = Storage;
