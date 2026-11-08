/**
 * Wave — Authentication Module
 * Handles login, registration, token management, session state,
 * and syncs guest history to MongoDB Atlas upon login.
 */

const Auth = {
    init() {
        const token = localStorage.getItem('wave_access_token');
        const userData = localStorage.getItem('wave_user');

        if (token && userData) {
            try {
                AppState.user = JSON.parse(userData);
                AppState.isAuthenticated = true;
                this.showApp();
                this.updateUI();
                this.syncLocalHistoryToCloud();
                // Re-fetch recently played from cloud now that auth is restored
                if (typeof loadHomeRecentlyPlayed === 'function') {
                    loadHomeRecentlyPlayed();
                }
            } catch {
                this.showAuthModal();
            }
        } else {
            this.showAuthModal();
        }

        this.bindEvents();
    },

    bindEvents() {
        // Login form
        document.getElementById('login-form')?.addEventListener('submit', (e) => {
            e.preventDefault();
            this.login();
        });

        // Register form
        document.getElementById('register-form')?.addEventListener('submit', (e) => {
            e.preventDefault();
            this.register();
        });

        // Toggle between login/register
        document.getElementById('show-register')?.addEventListener('click', (e) => {
            e.preventDefault();
            document.getElementById('login-form')?.classList.add('hidden');
            document.getElementById('register-form')?.classList.remove('hidden');
            document.getElementById('login-error')?.classList.add('hidden');
            document.getElementById('register-error')?.classList.add('hidden');
        });

        document.getElementById('show-login')?.addEventListener('click', (e) => {
            e.preventDefault();
            document.getElementById('register-form')?.classList.add('hidden');
            document.getElementById('login-form')?.classList.remove('hidden');
            document.getElementById('login-error')?.classList.add('hidden');
            document.getElementById('register-error')?.classList.add('hidden');
        });

        // Logout
        document.getElementById('btn-logout')?.addEventListener('click', () => {
            this.logout();
        });
    },

    async login() {
        const email = document.getElementById('login-email').value.trim();
        const password = document.getElementById('login-password').value;
        const errorEl = document.getElementById('login-error');
        const btn = document.getElementById('login-btn');

        errorEl.classList.add('hidden');
        btn.textContent = 'Signing in...';
        btn.disabled = true;

        try {
            const data = await API.post('/api/auth/login', { email, password });

            if (data && data.access_token) {
                this.saveSession(data);
                this.showApp();
                this.updateUI();
                this.syncLocalHistoryToCloud();
                showToast(`Welcome back, ${data.user.display_name || data.user.username}!`, 'success');

                // Refresh library & home
                if (typeof Library !== 'undefined') {
                    Library.loadPlaylistsNav();
                }
                if (typeof loadHomeRecentlyPlayed === 'function') {
                    loadHomeRecentlyPlayed();
                }
            }
        } catch (error) {
            let msg = error.message || 'Login failed';
            if (msg.includes('Failed to fetch') || msg.includes('NetworkError')) {
                msg = 'Cannot connect to server. Please verify the Python backend is running.';
            }
            errorEl.textContent = msg;
            errorEl.classList.remove('hidden');
        } finally {
            btn.textContent = 'Sign In';
            btn.disabled = false;
        }
    },

    async register() {
        const username = document.getElementById('register-username').value.trim();
        const email = document.getElementById('register-email').value.trim();
        const password = document.getElementById('register-password').value;
        const errorEl = document.getElementById('register-error');
        const btn = document.getElementById('register-btn');

        errorEl.classList.add('hidden');
        btn.textContent = 'Creating account...';
        btn.disabled = true;

        try {
            const data = await API.post('/api/auth/register', {
                username,
                email,
                password,
            });

            if (data && data.access_token) {
                this.saveSession(data);
                this.showApp();
                this.updateUI();
                this.syncLocalHistoryToCloud();
                showToast(`Welcome to Wave, ${data.user.display_name || data.user.username}!`, 'success');

                if (typeof Library !== 'undefined') {
                    Library.loadPlaylistsNav();
                }
            }
        } catch (error) {
            let msg = error.message || 'Registration failed';
            if (msg.includes('Failed to fetch') || msg.includes('NetworkError')) {
                msg = 'Cannot connect to server. Please verify the Python backend is running.';
            }
            errorEl.textContent = msg;
            errorEl.classList.remove('hidden');
        } finally {
            btn.textContent = 'Create Account';
            btn.disabled = false;
        }
    },

    saveSession(data) {
        localStorage.setItem('wave_access_token', data.access_token);
        localStorage.setItem('wave_refresh_token', data.refresh_token);
        localStorage.setItem('wave_user', JSON.stringify(data.user));

        AppState.user = data.user;
        AppState.isAuthenticated = true;
    },

    _refreshPromise: null,

    async refreshToken() {
        const refreshToken = localStorage.getItem('wave_refresh_token');
        if (!refreshToken) {
            this.logout();
            return false;
        }

        if (this._refreshPromise) {
            return this._refreshPromise;
        }

        this._refreshPromise = (async () => {
            try {
                const response = await fetch(`${API.baseUrl || ''}/api/auth/refresh`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ refresh_token: refreshToken }),
                });

                if (response.ok) {
                    const data = await response.json();
                    this.saveSession(data);
                    return true;
                } else {
                    this.logout();
                    return false;
                }
            } catch (error) {
                console.error('Token refresh network error:', error);
                return false;
            } finally {
                this._refreshPromise = null;
            }
        })();

        return this._refreshPromise;
    },

    logout() {
        const refreshToken = localStorage.getItem('wave_refresh_token');
        if (refreshToken) {
            fetch(`${API.baseUrl || ''}/api/auth/logout`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ refresh_token: refreshToken }),
            }).catch(() => {});
        }

        localStorage.removeItem('wave_access_token');
        localStorage.removeItem('wave_refresh_token');
        localStorage.removeItem('wave_user');

        AppState.user = null;
        AppState.isAuthenticated = false;

        this.showAuthModal();
        showToast('Logged out', 'info');
    },

    showAuthModal() {
        document.getElementById('auth-overlay')?.classList.remove('hidden');
    },

    showApp() {
        document.getElementById('auth-overlay')?.classList.add('hidden');
    },

    updateUI() {
        const user = AppState.user;
        if (!user) return;

        const nameEl = document.getElementById('user-display-name');
        if (nameEl) {
            nameEl.textContent = user.display_name || user.username || 'User';
        }

        const avatarEl = document.getElementById('user-avatar');
        if (avatarEl && user.avatar_url) {
            avatarEl.innerHTML = `<img src="${user.avatar_url}" alt="Avatar" style="width:100%;height:100%;object-fit:cover;border-radius:50%;">`;
        }
    },

    // Sync any guest played tracks to MongoDB Atlas
    async syncLocalHistoryToCloud() {
        try {
            const raw = localStorage.getItem('wave_recently_played');
            if (raw) {
                const list = JSON.parse(raw);
                for (const t of list.slice(0, 10)) {
                    API.post('/api/history', {
                        video_id: t.video_id,
                        title: t.title || t.track_name || 'Unknown',
                        artist: t.artist || 'Unknown',
                        thumbnail: t.thumbnail || t.album_art || '',
                    }).catch(() => {});
                }
            }
        } catch {}
    }
};
