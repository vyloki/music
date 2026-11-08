/**
 * Wave — Main Application Logic
 * SPA routing, state management, API client, Home feed loader, search,
 * artist profiles, and persistent recently played rendering.
 */

// ============================================
// API Client
// ============================================

const API = {
    baseUrl: (function() {
        if (typeof window !== 'undefined') {
            const stored = localStorage.getItem('wave_server_url');
            if (stored) return stored.replace(/\/+$/, '');
            const isNative = window.Capacitor !== undefined || 
                             window.location.protocol === 'capacitor:' || 
                             window.location.protocol === 'ionic:';
            if (isNative && window.WAVE_SERVER_URL) {
                return window.WAVE_SERVER_URL.replace(/\/+$/, '');
            }
        }
        return '';
    })(),

    setBaseUrl(url) {
        this.baseUrl = (url || '').replace(/\/+$/, '');
        if (typeof localStorage !== 'undefined') {
            if (this.baseUrl) {
                localStorage.setItem('wave_server_url', this.baseUrl);
            } else {
                localStorage.removeItem('wave_server_url');
            }
        }
    },

    getHeaders() {
        const headers = { 'Content-Type': 'application/json' };
        const token = localStorage.getItem('wave_access_token');
        if (token) {
            headers['Authorization'] = `Bearer ${token}`;
        }
        return headers;
    },

    async request(method, url, body = null) {
        const options = {
            method,
            headers: this.getHeaders(),
        };
        if (body) {
            options.body = JSON.stringify(body);
        }

        try {
            let response = await fetch(`${this.baseUrl}${url}`, options);

            // Handle token expiry
            if (response.status === 401 && !url.includes('/api/auth/login') && !url.includes('/api/auth/register') && !url.includes('/api/auth/refresh')) {
                const refreshed = await Auth.refreshToken();
                if (refreshed) {
                    options.headers = this.getHeaders();
                    response = await fetch(`${this.baseUrl}${url}`, options);
                } else {
                    Auth.logout();
                    return null;
                }
            }

            if (!response.ok) {
                const error = await response.json().catch(() => ({}));
                let errorMsg = `HTTP ${response.status}`;
                if (Array.isArray(error.detail)) {
                    errorMsg = error.detail.map(d => d.msg || `${d.loc?.slice(-1)}: invalid`).join(', ');
                } else if (typeof error.detail === 'string') {
                    errorMsg = error.detail;
                } else if (error.message) {
                    errorMsg = error.message;
                }
                throw new Error(errorMsg);
            }

            return await response.json();
        } catch (error) {
            console.debug(`API Error [${method} ${url}]:`, error);
            throw error;
        }
    },

    get(url) { return this.request('GET', url); },
    post(url, body) { return this.request('POST', url, body); },
    put(url, body) { return this.request('PUT', url, body); },
    delete(url) { return this.request('DELETE', url); },
};


// ============================================
// App State
// ============================================

const AppState = {
    currentPage: 'home',
    user: null,
    isAuthenticated: false,
    searchResults: [],
    searchTimeout: null,
    categories: [],
    currentArtist: null,
};


// ============================================
// Toast Notifications
// ============================================

function showToast(message, type = 'info', duration = 3000) {
    const container = document.getElementById('toast-container');
    if (!container) return;
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    container.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(100%)';
        toast.style.transition = 'all 0.3s ease';
        setTimeout(() => toast.remove(), 300);
    }, duration);
}


// ============================================
// Navigation / Routing
// ============================================

let isNavigatingProgrammatically = false;

function navigateTo(page, updateHash = true, extra = {}) {
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));

    const targetPage = document.getElementById(`page-${page}`);
    if (targetPage) {
        targetPage.classList.add('active');
    }

    document.querySelectorAll('.nav-item').forEach(item => {
        item.classList.toggle('active', item.dataset.page === page);
    });

    AppState.currentPage = page;
    try {
        sessionStorage.setItem('wave_active_page', page);
    } catch (e) {}

    if (updateHash) {
        isNavigatingProgrammatically = true;
        if (page === 'search') {
            const q = extra.query || AppState.lastSearchQuery || '';
            window.location.hash = q ? ('#search?q=' + encodeURIComponent(q)) : '#search';
        } else if (page === 'library') {
            window.location.hash = '#library';
        } else if (page === 'extract') {
            window.location.hash = '#extract';
        } else if (page === 'queue') {
            window.location.hash = '#queue';
        } else if (page === 'home') {
            window.location.hash = '#home';
        } else if (page === 'artist-detail') {
            const name = extra.artistName || AppState.currentArtistName || AppState.currentArtist?.artist || AppState.currentArtist?.name || '';
            window.location.hash = name ? ('#artist?name=' + encodeURIComponent(name)) : '#artist';
        } else if (page === 'playlist-detail') {
            const id = extra.playlistId || AppState.currentPlaylist?._id || '';
            window.location.hash = id ? ('#playlist?id=' + encodeURIComponent(id)) : '#playlist';
        }
        setTimeout(() => {
            isNavigatingProgrammatically = false;
        }, 120);
    }

    if (page === 'search') {
        setTimeout(() => {
            document.getElementById('search-input')?.focus();
        }, 100);
    } else if (page === 'library') {
        if (typeof Library !== 'undefined') {
            Library.renderTabContent();
        }
    } else if (page === 'extract') {
        if (typeof Extract !== 'undefined') {
            Extract.loadHistory();
        }
    } else if (page === 'queue') {
        if (typeof Player !== 'undefined') {
            Player.renderQueue();
        }
    } else if (page === 'home') {
        loadHomeRecentlyPlayed();
    }
}


// ============================================
// Home Page Feed & Categories
// ============================================

async function initHomeFeed() {
    updateGreeting();
    loadHomeRecentlyPlayed();
    loadFeaturedArtists();

    try {
        const feed = await API.get('/api/recommendations/feed');
        if (feed) {
            if (feed.time_context) {
                const tc = feed.time_context;
                const greetingEl = document.getElementById('greeting-time');
                if (greetingEl) {
                    const cleanGreeting = (tc.greeting || 'Day').replace(/^Good\s+/i, '');
                    greetingEl.textContent = cleanGreeting.charAt(0).toUpperCase() + cleanGreeting.slice(1);
                }
                const moodTitleEl = document.getElementById('mood-title');
                if (moodTitleEl) moodTitleEl.textContent = tc.title || 'Today\'s Vibe';
                const moodSubEl = document.getElementById('mood-subtitle');
                if (moodSubEl) moodSubEl.textContent = tc.subtitle || 'Curated for right now';
            }

            if (feed.categories) {
                AppState.categories = feed.categories;
                renderCategoryPills(feed.categories);
                renderSearchBrowseTags(feed.categories);
            }

            // Contextual Mood Mix
            if (feed.mood_mix && feed.mood_mix.length > 0) {
                renderTrackCards(feed.mood_mix, 'mood-scroll');
                const btnMood = document.getElementById('btn-mood-play-all');
                if (btnMood) {
                    btnMood.onclick = () => {
                        if (typeof Player !== 'undefined') {
                            Player.setQueue(feed.mood_mix, 0);
                            Player.play(feed.mood_mix[0]);
                            showToast('Playing Time-of-Day Mood Mix', 'info');
                        }
                    };
                }
            }

            // Made For You Personalized Mix
            if (feed.for_you && feed.for_you.length > 0) {
                renderTrackCards(feed.for_you, 'for-you-scroll');
                const btnForYou = document.getElementById('btn-foryou-play-all');
                if (btnForYou) {
                    btnForYou.onclick = () => {
                        if (typeof Player !== 'undefined') {
                            Player.setQueue(feed.for_you, 0);
                            Player.play(feed.for_you[0]);
                            showToast('Playing Made For You Mix', 'info');
                        }
                    };
                }
            }

            // Trending Hits
            if (feed.trending && feed.trending.length > 0) {
                renderTrackCards(feed.trending, 'trending-scroll');
            }
            // Language & Mood Carousels
            if (feed.telugu && feed.telugu.length > 0) {
                renderTrackCards(feed.telugu, 'telugu-scroll');
            }
            if (feed.hindi && feed.hindi.length > 0) {
                renderTrackCards(feed.hindi, 'hindi-scroll');
            }
            if (feed.english && feed.english.length > 0) {
                renderTrackCards(feed.english, 'english-scroll');
            }
            if (feed.lofi && feed.lofi.length > 0) {
                renderTrackCards(feed.lofi, 'lofi-scroll');
            }
        }
    } catch (e) {
        console.debug('Home feed error:', e);
    }
}

// ============================================
// Featured Artists & Artist Profiles
// ============================================

async function loadFeaturedArtists() {
    const container = document.getElementById('artists-scroll');
    if (!container) return;

    try {
        const artists = await API.get('/api/artists/featured');
        if (artists && artists.length > 0) {
            container.innerHTML = artists.map(artist => `
                <div class="artist-card" onclick="openArtistPage('${escapeHtml(artist.name)}')">
                    <div class="artist-card-avatar">
                        <img src="${artist.image}" alt="${escapeHtml(artist.name)}" loading="lazy" onerror="this.src='https://cdn-images.dzcdn.net/images/artist/fbe3e1d17fc6958e047f011f74233f82/500x500-000000-80-0-0.jpg'">
                    </div>
                    <div class="artist-card-name">${escapeHtml(artist.name)}</div>
                </div>
            `).join('');
        }
    } catch (e) {
        console.debug('Failed to load featured artists:', e);
    }
}

async function openArtistPage(artistName, language = 'All') {
    if (!artistName || artistName === 'Unknown Artist' || artistName === 'Wave Music') return;

    AppState.currentArtistName = artistName;
    navigateTo('artist-detail', true, { artistName });
    window.scrollTo({ top: 0, behavior: 'instant' });

    const nameEl = document.getElementById('artist-detail-name');
    const genreEl = document.getElementById('artist-detail-genre');
    const metaEl = document.getElementById('artist-detail-meta');
    const avatarEl = document.getElementById('artist-detail-avatar');
    const listEl = document.getElementById('artist-track-list');
    const sectionTitle = document.getElementById('artist-songs-section-title');

    if (nameEl) nameEl.textContent = artistName;
    if (genreEl) genreEl.textContent = '';
    if (metaEl) metaEl.textContent = 'Fetching songs...';
    if (listEl) {
        listEl.innerHTML = `
            <div class="loading-state">
                <div class="loader">
                    <div class="loader-bar"></div>
                    <div class="loader-bar"></div>
                    <div class="loader-bar"></div>
                </div>
                <p>Loading songs by ${escapeHtml(artistName)}...</p>
            </div>
        `;
    }

    try {
        const langParam = language && language !== 'All' ? `?language=${encodeURIComponent(language)}` : '';
        const data = await API.get(`/api/artists/${encodeURIComponent(artistName)}${langParam}`);
        if (data) {
            AppState.currentArtist = data;

            if (nameEl) nameEl.textContent = data.artist;
            if (genreEl) genreEl.textContent = '';
            if (metaEl) metaEl.textContent = `${data.total_tracks || data.tracks?.length || 0} songs available`;

            if (avatarEl && data.image) {
                avatarEl.innerHTML = `<img src="${data.image}" alt="${escapeHtml(data.artist)}" onerror="this.src='https://cdn-images.dzcdn.net/images/artist/fbe3e1d17fc6958e047f011f74233f82/500x500-000000-80-0-0.jpg'">`;
            }

            // Render Language Pills above Popular Songs
            renderArtistLanguageFilter(data.languages, data.selected_language || language, data.artist);

            if (sectionTitle) {
                sectionTitle.textContent = (data.selected_language && data.selected_language !== 'All') 
                    ? `Popular ${data.selected_language} Songs` 
                    : 'Popular Songs';
            }

            if (data.tracks && data.tracks.length > 0) {
                renderArtistTracks(data.tracks);

                // Bind Play All & Shuffle
                document.getElementById('btn-play-artist-all').onclick = () => {
                    Player.setQueue(data.tracks, 0);
                    Player.play(data.tracks[0]);
                };

                document.getElementById('btn-shuffle-artist').onclick = () => {
                    Player.setQueue(data.tracks, 0);
                    Player.shuffleEnabled = true;
                    Player.play(data.tracks[Math.floor(Math.random() * data.tracks.length)]);
                };
            } else {
                if (listEl) {
                    listEl.innerHTML = `<div class="empty-state"><p>No ${language !== 'All' ? language + ' ' : ''}songs found for ${escapeHtml(artistName)}</p></div>`;
                }
            }
        }
    } catch (error) {
        if (listEl) {
            listEl.innerHTML = `<div class="empty-state"><p>Failed to load songs for ${escapeHtml(artistName)}</p></div>`;
        }
    }
}

function renderArtistLanguageFilter(languages, activeLang, artistName) {
    const bar = document.getElementById('artist-language-filter-bar');
    if (!bar) return;

    if (!languages || languages.length <= 1) {
        bar.innerHTML = '';
        return;
    }

    const current = (activeLang || 'All').toLowerCase();
    bar.innerHTML = languages.map(lang => {
        const isActive = lang.toLowerCase() === current;
        return `
            <button class="artist-lang-pill ${isActive ? 'active' : ''}"
                    onclick="filterArtistByLanguage('${escapeHtml(artistName)}', '${escapeHtml(lang)}')">
                ${escapeHtml(lang)}
            </button>
        `;
    }).join('');
}

async function filterArtistByLanguage(artistName, language) {
    const listEl = document.getElementById('artist-track-list');
    const sectionTitle = document.getElementById('artist-songs-section-title');

    // Update active pill UI immediately
    document.querySelectorAll('.artist-lang-pill').forEach(pill => {
        pill.classList.toggle('active', pill.textContent.trim().toLowerCase() === language.toLowerCase());
    });

    if (sectionTitle) {
        sectionTitle.textContent = (language && language !== 'All') ? `Popular ${language} Songs` : 'Popular Songs';
    }

    if (listEl) {
        listEl.innerHTML = `
            <div class="loading-state">
                <div class="loader">
                    <div class="loader-bar"></div>
                    <div class="loader-bar"></div>
                    <div class="loader-bar"></div>
                </div>
                <p>Loading ${escapeHtml(language)} songs by ${escapeHtml(artistName)}...</p>
            </div>
        `;
    }

    try {
        const langParam = language && language !== 'All' ? `?language=${encodeURIComponent(language)}` : '';
        const data = await API.get(`/api/artists/${encodeURIComponent(artistName)}${langParam}`);
        if (data && data.tracks) {
            AppState.currentArtist = data;
            const metaEl = document.getElementById('artist-detail-meta');
            if (metaEl) metaEl.textContent = `${data.total_tracks || data.tracks.length} songs available`;

            if (data.tracks.length > 0) {
                renderArtistTracks(data.tracks);
            } else {
                listEl.innerHTML = `<div class="empty-state"><p>No ${escapeHtml(language)} songs found for ${escapeHtml(artistName)}</p></div>`;
            }
        }
    } catch (e) {
        if (listEl) listEl.innerHTML = `<div class="empty-state"><p>Failed to load ${escapeHtml(language)} songs</p></div>`;
    }
}

function renderArtistTracks(tracks) {
    const listEl = document.getElementById('artist-track-list');
    if (!listEl) return;

    listEl.innerHTML = `
        <div class="track-list">
            ${tracks.map((track, index) => {
                const meta = typeof getTrackMetadata === 'function' ? getTrackMetadata(track) : { title: track.track_name || track.title, movie: '', language: '', artist: track.artist, subtitle: track.artist };
                const sub = meta.movie ? (meta.language ? `${meta.movie} • ${meta.language}` : meta.movie) : (meta.language ? `${meta.artist} • ${meta.language}` : meta.artist);
                return `
                <div class="track-row"
                     data-video-id="${track.video_id}"
                     onclick="playTrackFromArtist(${index})">
                    <div class="track-row-art">
                        <img src="${track.thumbnail || track.album_art || ''}"
                             alt="" loading="lazy"
                             onerror="this.style.display='none'">
                    </div>
                    <div class="track-row-info">
                        <div class="track-row-title">${escapeHtml(meta.title)}</div>
                        <div class="track-row-artist">${escapeHtml(sub)}</div>
                    </div>
                    <div class="track-row-duration">${formatDuration(track.duration)}</div>
                    <div class="track-row-actions">
                        <button class="btn-icon" onclick="event.stopPropagation(); downloadSong('${track.video_id}', '${escapeHtml(meta.title)}', '${escapeHtml(meta.movie || meta.artist)}')" title="Download">
                            <i data-lucide="download"></i>
                        </button>
                        <button class="btn-icon" onclick="event.stopPropagation(); addToQueueFromArtist(${index})" title="Add to queue">
                            <i data-lucide="list-plus"></i>
                        </button>
                        <button class="btn-icon" onclick="event.stopPropagation(); Library.openAddToPlaylistModal('${track.video_id}', ${JSON.stringify(track).replace(/"/g, '&quot;')})" title="Add to playlist">
                            <i data-lucide="plus"></i>
                        </button>
                    </div>
                </div>
            `;}).join('')}
        </div>
    `;

    lucide.createIcons({ nodes: [listEl] });
}

function playTrackFromArtist(index) {
    if (AppState.currentArtist?.tracks) {
        Player.setQueue(AppState.currentArtist.tracks, index);
        Player.play(AppState.currentArtist.tracks[index]);
    }
}

function addToQueueFromArtist(index) {
    if (AppState.currentArtist?.tracks) {
        const track = AppState.currentArtist.tracks[index];
        Player.addToQueue(track);
        showToast(`Added "${track.track_name || track.title}" to queue`, 'success');
    }
}


function renderCategoryPills(categories) {
    const container = document.getElementById('home-categories');
    if (!container) return;

    container.innerHTML = categories.map(cat => `
        <button class="category-pill" onclick="loadCategoryTracks('${cat.id}')">
            <span>${escapeHtml(cat.name)}</span>
        </button>
    `).join('');
}

function renderSearchBrowseTags(categories) {
    const container = document.getElementById('search-browse-tags');
    if (!container) return;

    container.innerHTML = categories.map(cat => `
        <button class="category-pill" onclick="searchForCategory('${escapeHtml(cat.name)}')">
            <span>${escapeHtml(cat.name)}</span>
        </button>
    `).join('');
}

function searchForCategory(categoryName) {
    const input = document.getElementById('search-input');
    if (input) {
        input.value = categoryName;
        document.getElementById('search-clear')?.classList.remove('hidden');
        performSearch(categoryName);
    }
}

async function loadCategoryTracks(categoryId) {
    const cat = AppState.categories.find(c => c.id === categoryId);
    if (cat) {
        navigateTo('search');
        searchForCategory(cat.name);
    }
}

// ============================================
// Dual-Layer Recently Played (Local + Cloud)
// ============================================

async function loadHomeRecentlyPlayed() {
    const container = document.getElementById('recent-scroll');
    if (!container) return;

    let tracks = [];

    // 1. First load from localStorage (instant, never lost across logouts)
    try {
        const raw = localStorage.getItem('wave_recently_played');
        if (raw) {
            tracks = JSON.parse(raw);
        }
    } catch (e) {}

    // 2. If authenticated, attempt to fetch from MongoDB Atlas
    if (AppState.isAuthenticated) {
        try {
            const data = await API.get('/api/history?limit=10');
            if (data && data.history && data.history.length > 0) {
                const cloudTracks = data.history.map(h => ({
                    video_id: h.video_id,
                    title: h.title,
                    track_name: h.title,
                    artist: h.artist,
                    thumbnail: h.thumbnail,
                    album_art: h.thumbnail,
                    duration: 0,
                    // Include frozen display metadata from DB so rendering never re-parses
                    movie: h.movie || '',
                    language: h.language || '',
                    subtitle: h.subtitle || '',
                }));

                // Merge deduplicating by video_id (local first, then cloud)
                const seen = new Set();
                const merged = [];
                for (const t of [...tracks, ...cloudTracks]) {
                    if (t && t.video_id && !seen.has(t.video_id)) {
                        seen.add(t.video_id);
                        merged.push(t);
                    }
                }
                tracks = merged.slice(0, 15);

                // Persist merged result to localStorage for offline resilience
                try {
                    localStorage.setItem('wave_recently_played', JSON.stringify(tracks));
                } catch (e) {}
            }
        } catch (e) {}
    }

    if (tracks.length > 0) {
        renderTrackCards(tracks, 'recent-scroll');
    } else {
        container.innerHTML = `
            <div class="empty-state-card">
                <i data-lucide="music"></i>
                <p>Play a song to see it here</p>
            </div>
        `;
        lucide.createIcons({ nodes: [container] });
    }
}


// ============================================
// Search Functionality
// ============================================

let searchDebounceTimer = null;

async function performSearch(query, updateHash = true) {
    if (!query || query.trim().length === 0) return;

    const trimmed = query.trim();
    const resultsContainer = document.getElementById('search-results');
    const loadingEl = document.getElementById('search-loading');
    const suggestionsEl = document.getElementById('search-suggestions');
    const browseTagsEl = document.getElementById('search-browse-tags');
    const filterTabsEl = document.getElementById('search-filter-tabs');

    suggestionsEl?.classList.add('hidden');
    browseTagsEl?.classList.add('hidden');
    filterTabsEl?.classList.add('hidden');
    loadingEl?.classList.remove('hidden');
    resultsContainer.innerHTML = '';

    // Reset filter to 'all'
    document.querySelectorAll('.search-filter-btn').forEach(b => b.classList.remove('active'));
    document.querySelector('.search-filter-btn[data-filter="all"]')?.classList.add('active');
    AppState.activeSearchFilter = 'all';
    AppState.lastSearchQuery = trimmed;

    try {
        sessionStorage.setItem('wave_last_search_query', trimmed);
        sessionStorage.setItem('wave_active_page', 'search');
    } catch (e) {}

    if (updateHash) {
        window.location.hash = '#search?q=' + encodeURIComponent(trimmed);
    }

    try {
        const data = await API.get(`/api/search?q=${encodeURIComponent(trimmed)}&limit=30`);

        loadingEl?.classList.add('hidden');

        if (data && data.results && data.results.length > 0) {
            AppState.searchResults = data.results;
            try {
                sessionStorage.setItem('wave_last_search_results', JSON.stringify(data.results));
            } catch (e) {}
            filterTabsEl?.classList.remove('hidden');
            renderSearchResults(data.results, 'all');
        } else {
            resultsContainer.innerHTML = `
                <div class="empty-state">
                    <i data-lucide="search-x"></i>
                    <p>No results found for "${escapeHtml(trimmed)}"</p>
                </div>
            `;
            lucide.createIcons({ nodes: [resultsContainer] });
        }
    } catch (error) {
        loadingEl?.classList.add('hidden');
        resultsContainer.innerHTML = `
            <div class="empty-state">
                <i data-lucide="wifi-off"></i>
                <p>Search failed. Please verify the Python server is running.</p>
            </div>
        `;
        lucide.createIcons({ nodes: [resultsContainer] });
    }
}
// Classify a track on frontend (fallback if backend didn't classify)
function classifyTrack(track) {
    if (track.track_type && ['song', 'bgm', 'playlist'].includes(track.track_type)) {
        return track.track_type;
    }
    // Fallback classification
    const title = (track.title || track.track_name || '').toLowerCase();
    const dur = track.duration || 0;
    const playlistKw = ['jukebox', 'playlist', 'top 10', 'top 20', 'best of', 'collection',
        'hits', 'mashup', 'medley', 'nonstop', 'non stop', 'superhits', 'super hits',
        'full album', 'back to back', 'vol ', 'vol.', 'evergreen'];
    const bgmKw = ['bgm', 'background music', 'instrumental', 'theme music', 'ost', 'ringtone'];
    if (dur > 600 || playlistKw.some(k => title.includes(k))) return 'playlist';
    if (bgmKw.some(k => title.includes(k))) return 'bgm';
    return 'song';
}

// ============================================
// Movie Name & Language Metadata Parser (Frontend Dual-Layer)
// ============================================

function getTrackMetadata(track) {
    if (track.movie && track.language) {
        return {
            title: track.track_name || track.title || 'Unknown',
            movie: track.movie,
            language: track.language,
            artist: track.artist || 'Unknown',
            subtitle: track.subtitle || `${track.movie} • ${track.language}`,
        };
    }

    const rawTitle = track.title || track.track_name || 'Unknown';
    const uploader = track.artist || '';
    const query = AppState.lastSearchQuery || '';

    // Detect language
    const combined = `${rawTitle} ${uploader} ${query}`.toLowerCase();
    const langMap = {
        telugu: 'Telugu', tamil: 'Tamil', hindi: 'Hindi',
        malayalam: 'Malayalam', kannada: 'Kannada', punjabi: 'Punjabi',
        english: 'English', bengali: 'Bengali', bangla: 'Bengali',
        marathi: 'Marathi', gujarati: 'Gujarati', bhojpuri: 'Bhojpuri',
        korean: 'Korean', spanish: 'Spanish', japanese: 'Japanese'
    };
    let language = track.language || '';
    if (!language) {
        for (const [k, v] of Object.entries(langMap)) {
            if (new RegExp(`\\b${k}\\b`, 'i').test(combined)) {
                language = v;
                break;
            }
        }
        if (!language) {
            const uplLower = uploader.toLowerCase();
            if (/think music telugu|aditya music|mango music|lahari|saregama telugu|zee music telugu|madhura|t-series telugu/i.test(uplLower)) {
                language = 'Telugu';
            } else if (/think music india|think music tamil|sun pictures|divo|u1 records|sony music south|saregama tamil|behindwoods|sony music tamil|zee music tamil|tips tamil/i.test(uplLower)) {
                language = 'Tamil';
            } else if (/t-series|zee music|yrf|sony music india|tips official|eros now|saregama music/i.test(uplLower)) {
                language = 'Hindi';
            } else if (/muzik247|123musix|goodwill|saregama malayalam/i.test(uplLower)) {
                language = 'Malayalam';
            } else if (/anand audio|jhankar|a2 music/i.test(uplLower)) {
                language = 'Kannada';
            } else if (/speed records|apna punjab|geet mp3/i.test(uplLower)) {
                language = 'Punjabi';
            }
        }
    }

    // Clean noise tags
    const cleanPart = (text) => {
        let s = text || '';
        const noise = [
            /\(Official\s*(Music\s*)?Video\)/gi, /\[Official\s*(Music\s*)?Video\]/gi,
            /\(Official\s*Audio\)/gi, /\[Official\s*Audio\]/gi,
            /\(Official\s*Song\)/gi, /\[Official\s*Song\]/gi,
            /\(Official\s*Lyric\s*Video\)/gi, /\[Official\s*Lyric\s*Video\]/gi,
            /\(Official\)/gi, /\[Official\]/gi,
            /\(Lyric\s*Video\)/gi, /\[Lyric\s*Video\]/gi,
            /\(Lyrical\s*Video\)/gi, /\[Lyrical\s*Video\]/gi,
            /\bLyrical\s*Video\b/gi, /\bLyric\s*Video\b/gi,
            /\(Audio\)/gi, /\[Audio\]/gi, /\(Visualizer\)/gi, /\[Visualizer\]/gi,
            /\(Video\)/gi, /\[Video\]/gi,
            /4K\s*Ultra\s*HD\s*Video\s*Song/gi, /4K\s*Video\s*Song/gi,
            /4K\s*Full\s*Video/gi, /4K\s*Video/gi, /4K\s*Song/gi, /\b4K\b/gi, /\b8K\b/gi,
            /Full\s*HD\s*Video\s*Song/gi, /Full\s*HD\s*Video/gi,
            /\bFull\s*Video\s*Song\b/gi, /\bVideo\s*Song\b/gi,
            /\bFull\s*Song\b/gi, /\bFull\s*Video\b/gi,
            /\bHD\s*Video\b/gi, /\bHD\s*Song\b/gi, /\bHD\b/gi,
            /Official\s*Video/gi, /Official\s*Song/gi, /Music\s*Video/gi,
            /Promotional\s*Video/gi, /Promo\s*Video/gi, /Promo\s*Song/gi,
            /\(Unplugged\)/gi, /\[Unplugged\]/gi, /\bUnplugged\s*Version\b/gi, /\bUnplugged\b/gi,
            /\(Remastered\)/gi, /\[Remastered\]/gi, /\bRemastered\b/gi,
            /\(Movie\s*Version\)/gi, /\[Movie\s*Version\]/gi, /\bMovie\s*Version\b/gi,
            /\(Film\s*Version\)/gi, /\[Film\s*Version\]/gi, /\bFilm\s*Version\b/gi,
            /\(8D\s*Audio\)/gi, /\[8D\s*Audio\]/gi, /\b8D\s*Audio\b/gi,
            /\(Bass\s*Boosted\)/gi, /\[Bass\s*Boosted\]/gi, /\bBass\s*Boosted\b/gi,
            /\(Slowed\s*\+?\s*Reverb\)/gi, /\[Slowed\s*\+?\s*Reverb\]/gi, /\bSlowed\s*\+?\s*Reverb\b/gi,
            /\(Slowed\)/gi, /\[Slowed\]/gi, /\(Reverb\)/gi, /\[Reverb\]/gi,
            /\(Live\)/gi, /\[Live\]/gi, /\bLive\s*Version\b/gi,
            /\(Acoustic\)/gi, /\[Acoustic\]/gi, /\bAcoustic\s*Version\b/gi,
            /\(Cover\)/gi, /\[Cover\]/gi, /\bCover\s*Version\b/gi,
            /\(Lyrics\)/gi, /\[Lyrics\]/gi, /\(With\s*Lyrics\)/gi, /\[With\s*Lyrics\]/gi,
            /\(Full\)/gi, /\[Full\]/gi, /\(Audio\s*Jukebox\)/gi, /\[Audio\s*Jukebox\]/gi,
        ];
        noise.forEach(p => s = s.replace(p, ''));
        s = s.replace(/\(.*?Official.*?\)/gi, '');
        s = s.replace(/\[.*?Official.*?\]/gi, '');
        s = s.replace(/^[\s|\-:]+|[\s|\-:]+$/g, '');
        s = s.replace(/\s{2,}/g, ' ');
        return s.trim();
    };

    // Check for From "Movie"
    const fromMatch = rawTitle.match(/(?:\(|\[)?(?:From|from)\s*["']([^"']+)["'](?:\)|\])?/i);
    let movie = track.movie || (fromMatch ? fromMatch[1].trim() : '');

    let cleanedFull = rawTitle;
    if (fromMatch) {
        cleanedFull = rawTitle.replace(fromMatch[0], '');
    }

    let parts = [];
    const delims = ['||', '|', ' - ', ' – ', ' — '];
    for (const d of delims) {
        if (cleanedFull.includes(d)) {
            parts = cleanedFull.split(d).map(p => cleanPart(p)).filter(Boolean);
            break;
        }
    }
    if (parts.length === 0) {
        parts = [cleanPart(cleanedFull)].filter(Boolean);
    }

    let title = parts[0] || track.track_name || rawTitle;
    title = title.replace(/\((?:Telugu|Tamil|Hindi|Malayalam|Kannada|Punjabi|English)\)/gi, '').trim();
    title = title.replace(/\[(?:Telugu|Tamil|Hindi|Malayalam|Kannada|Punjabi|English)\]/gi, '').trim();

    let artist = uploader || 'Unknown Artist';
    let isArtistTrack = false;

    if (cleanedFull.includes(' - ') && !fromMatch && parts.length >= 2) {
        if (uploader.toLowerCase().includes(parts[0].toLowerCase()) || parts[0].toLowerCase().includes(uploader.toLowerCase())) {
            artist = parts[0];
            title = parts[1];
            isArtistTrack = true;
        }
    }

    if (!movie && !isArtistTrack && parts.length > 1) {
        let candidate = parts[1].replace(/\b(?:Telugu|Tamil|Hindi|Malayalam|Kannada|Punjabi|English)\b/gi, '').trim();
        candidate = candidate.replace(/^[\s|\-:]+|[\s|\-:]+$/g, '').trim();
        if (candidate && !/t-series|music|channel|records|video|subscribe|audio/i.test(candidate)) {
            movie = candidate;
            if (parts.length > 2 && !/t-series|channel|video|subscribe/i.test(parts[2])) {
                artist = parts[2];
            }
        }
    }

    if (!movie && !isArtistTrack && query) {
        const qWords = query.split(/\s+/).filter(w => !/songs|song|video|audio|telugu|tamil|hindi|mp3|all|best|hits/i.test(w));
        if (qWords.length > 0) {
            movie = qWords.map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
        }
    }

    artist = artist.replace(/ - Topic$/i, '').replace(/VEVO/gi, '').trim();

    let subtitle = '';
    if (movie) {
        subtitle = language ? `${movie} • ${language}` : movie;
    } else {
        subtitle = language ? `${artist} • ${language}` : artist;
    }

    return {
        title: title || rawTitle,
        movie: movie,
        language: language,
        artist: artist,
        subtitle: subtitle,
    };
}

// Render a single song row
function renderSongRow(track, globalIndex) {
    const meta = getTrackMetadata(track);
    const safeTrack = JSON.stringify({ ...track, track_name: meta.title, movie: meta.movie, language: meta.language, subtitle: meta.subtitle }).replace(/"/g, '&quot;');
    const name = escapeHtml(meta.title);
    const movie = escapeHtml(meta.movie);
    const language = escapeHtml(meta.language);
    const artist = escapeHtml(meta.artist);

    const subtitleHtml = meta.movie ? `
        <span class="track-movie" onclick="event.stopPropagation(); searchForCategory('${movie}')">${movie}</span>
        ${language ? `<span class="track-lang-dot">•</span><span class="track-lang-text">${language}</span>` : ''}
    ` : (meta.language ? `
        <span class="track-movie">${artist}</span>
        <span class="track-lang-dot">•</span><span class="track-lang-text">${language}</span>
    ` : `
        <span class="track-movie">${artist}</span>
    `);

    return `
        <div class="track-row" data-video-id="${track.video_id}" onclick="playTrackFromResults(${globalIndex})">
            <div class="track-row-art">
                <img src="${track.thumbnail || ''}" alt="" loading="lazy" onerror="this.style.display='none'">
            </div>
            <div class="track-row-info">
                <div class="track-row-title">${name}</div>
                <div class="track-row-artist">${subtitleHtml}</div>
            </div>
            <div class="track-row-duration">${formatDuration(track.duration)}</div>
            <div class="track-row-actions">
                <button class="btn-icon" onclick="event.stopPropagation(); downloadSong('${track.video_id}','${name}','${movie || artist}')" title="Download">
                    <i data-lucide="download"></i>
                </button>
                <button class="btn-icon" onclick="event.stopPropagation(); addToQueue(${globalIndex})" title="Add to queue">
                    <i data-lucide="list-plus"></i>
                </button>
                <button class="btn-icon" onclick="event.stopPropagation(); Library.openAddToPlaylistModal('${track.video_id}', ${safeTrack})" title="Add to playlist">
                    <i data-lucide="plus"></i>
                </button>
            </div>
        </div>
    `;
}

// Render a playlist card
function renderPlaylistCard(track, globalIndex) {
    const meta = getTrackMetadata(track);
    const name = escapeHtml(meta.title);
    const movie = escapeHtml(meta.movie);
    const language = escapeHtml(meta.language);
    const artist = escapeHtml(meta.artist);
    const dur = formatDuration(track.duration);

    const subtitleHtml = meta.movie ? `
        <span class="track-movie">${movie}</span>
        ${language ? `<span class="track-lang-dot">•</span><span class="track-lang-text">${language}</span>` : ''}
    ` : `<span>${artist}</span>`;

    return `
        <div class="playlist-result-card">
            <div class="playlist-result-thumb">
                <img src="${track.thumbnail || ''}" alt="" loading="lazy" onerror="this.style.display='none'">
                <div class="playlist-result-overlay">
                    <span class="playlist-badge"><i data-lucide="list-music"></i> ${dur}</span>
                </div>
            </div>
            <div class="playlist-result-info">
                <div class="playlist-result-title">${name}</div>
                <div class="playlist-result-artist">${subtitleHtml}</div>
            </div>
            <div class="playlist-result-actions">
                <button class="btn-primary-sm" onclick="playTrackFromResults(${globalIndex})" title="Play">
                    <i data-lucide="play"></i> Play
                </button>
            </div>
        </div>
    `;
}

// Render a section label
function renderSectionLabel(icon, label, count) {
    return `<div class="search-section-label"><i data-lucide="${icon}"></i><span>${label}</span><span class="section-count">${count}</span></div>`;
}

// ============================================
// Album Grouping Logic (Separate by Movie + Language)
// ============================================

/**
 * Extract a "movie name" from a track title.
 * Tries to find the search query inside the title, or falls back to artist.
 */
function extractMovieName(track, query) {
    const title = (track.track_name || track.title || '').toLowerCase();
    const q = (query || '').toLowerCase().trim();

    // If track has an album field, use it
    if (track.album && track.album.trim()) return track.album.trim();

    // Try to find the query keyword in the title
    if (q && title.includes(q)) {
        // Capitalise query words as the album name
        return query.split(' ').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
    }

    // Fallback: use the artist/channel as the album grouping key
    return track.artist || 'Unknown';
}

/**
 * Group songs into distinct albums separated by Movie AND Language.
 * (e.g. "Dude (Telugu)" vs "Dude (Tamil)")
 * Returns: [{albumName, movie, language, thumbnail, songs, totalDuration}]
 */
function groupAlbums(songs, query) {
    const map = new Map();

    songs.forEach(t => {
        const meta = getTrackMetadata(t);
        const movie = meta.movie || extractMovieName(t, query) || 'Album';
        const lang = meta.language || '';

        // Separate by Movie + Language!
        const key = `${movie.toLowerCase()}__${lang.toLowerCase()}`;
        const albumDisplayName = lang ? `${movie} (${lang})` : movie;

        if (!map.has(key)) {
            map.set(key, {
                albumName: albumDisplayName,
                movie: movie,
                language: lang,
                thumbnail: t.thumbnail || '',
                songs: [],
                totalDuration: 0,
            });
        }
        const album = map.get(key);
        album.songs.push(t);
        album.totalDuration += (t.duration || 0);
    });

    const albums = [...map.values()];

    // Sort: if user searched for a language, put that language album first, then sort by songs count
    const qLower = (query || '').toLowerCase();
    albums.sort((a, b) => {
        const aMatch = a.language && qLower.includes(a.language.toLowerCase());
        const bMatch = b.language && qLower.includes(b.language.toLowerCase());
        if (aMatch && !bMatch) return -1;
        if (!aMatch && bMatch) return 1;
        return b.songs.length - a.songs.length;
    });

    return albums;
}

/** Render album cards */
function renderAlbumCards(albums) {
    return albums.map((album, ai) => {
        const safeName = escapeHtml(album.albumName);
        const songCount = album.songs.length;
        const dur = formatDuration(album.totalDuration);
        const tracklist = album.songs.map((t, si) => renderSongRow(t, t._searchIndex)).join('');
        return `
            <div class="album-card" id="album-card-${ai}">
                <div class="album-card-header" onclick="toggleAlbum(${ai})">
                    <div class="album-card-art">
                        <img src="${album.thumbnail}" alt="" loading="lazy" onerror="this.style.display='none'">
                        <div class="album-card-art-overlay">
                            <i data-lucide="disc-3"></i>
                        </div>
                    </div>
                    <div class="album-card-meta">
                        <div class="album-card-name">${safeName}</div>
                        <div class="album-card-info">${songCount} song${songCount !== 1 ? 's' : ''} &nbsp;&bull;&nbsp; ${dur}</div>
                    </div>
                    <div class="album-card-actions">
                        <button class="btn-primary-sm" onclick="event.stopPropagation(); playAlbum(${ai})">
                            <i data-lucide="play"></i> Play All
                        </button>
                        <button class="btn-icon album-expand-btn" title="Expand">
                            <i data-lucide="chevron-down"></i>
                        </button>
                    </div>
                </div>
                <div class="album-tracklist hidden" id="album-tracklist-${ai}">
                    <div class="track-list">${tracklist}</div>
                </div>
            </div>
        `;
    }).join('');
}

// Store albums globally for playback
let _currentAlbums = [];

function toggleAlbum(ai) {
    const tracklist = document.getElementById(`album-tracklist-${ai}`);
    const card = document.getElementById(`album-card-${ai}`);
    if (!tracklist) return;
    const isOpen = !tracklist.classList.contains('hidden');
    tracklist.classList.toggle('hidden', isOpen);
    card?.classList.toggle('album-card-open', !isOpen);
}

function playAlbum(ai) {
    const album = _currentAlbums[ai];
    if (!album || !album.songs.length) return;
    if (typeof Player !== 'undefined') {
        Player.setQueue(album.songs, 0);
        Player.play(album.songs[0]);
        showToast(`Playing ${album.albumName}`, 'success');
    }
}


function renderSearchResults(results, filter) {
    const container = document.getElementById('search-results');
    const activeFilter = filter || AppState.activeSearchFilter || 'all';

    // Classify and bucket results, preserving original index for playback
    const songs = [], bgms = [], playlists = [];
    results.forEach((t, i) => {
        const type = classifyTrack(t);
        t._searchIndex = i; // store global index for playback
        if (type === 'bgm') bgms.push(t);
        else if (type === 'playlist') playlists.push(t);
        else songs.push(t);
    });

    let html = '';

    if (activeFilter === 'album') {
        // Group all songs into albums by movie name
        const albums = groupAlbums(songs, AppState.lastSearchQuery || '');
        _currentAlbums = albums;
        if (albums.length > 0) {
            html += `<div class="album-grid">${renderAlbumCards(albums)}</div>`;
        } else {
            html = `<div class="empty-state"><i data-lucide="disc-3"></i><p>No albums found — try searching a movie name</p></div>`;
        }
    } else {
        if (activeFilter === 'song' || activeFilter === 'all') {
            if (songs.length > 0) {
                if (activeFilter === 'all') html += renderSectionLabel('music', 'Songs', songs.length);
                html += `<div class="track-list">${songs.map(t => renderSongRow(t, t._searchIndex)).join('')}</div>`;
            }
        }

        if (activeFilter === 'playlist' || activeFilter === 'all') {
            if (playlists.length > 0) {
                if (activeFilter === 'all') html += renderSectionLabel('list-music', 'Playlists', playlists.length);
                html += `<div class="playlist-results-grid">${playlists.map(t => renderPlaylistCard(t, t._searchIndex)).join('')}</div>`;
            }
        }

        if (activeFilter === 'bgm' || activeFilter === 'all') {
            if (bgms.length > 0) {
                if (activeFilter === 'all') html += renderSectionLabel('waveform', 'BGMs & Instrumentals', bgms.length);
                html += `<div class="track-list">${bgms.map(t => renderSongRow(t, t._searchIndex)).join('')}</div>`;
            }
        }
    }

    if (!html) {
        const labels = { song: 'songs', bgm: 'BGMs', playlist: 'playlists', album: 'albums' };
        html = `<div class="empty-state"><i data-lucide="search-x"></i><p>No ${labels[activeFilter] || 'results'} found</p></div>`;
    }

    container.innerHTML = html;
    lucide.createIcons({ nodes: [container] });
}


// Filter tab click handler
document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('search-filter-tabs')?.addEventListener('click', (e) => {
        const btn = e.target.closest('.search-filter-btn');
        if (!btn) return;
        document.querySelectorAll('.search-filter-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        AppState.activeSearchFilter = btn.dataset.filter;
        if (AppState.searchResults?.length > 0) {
            renderSearchResults(AppState.searchResults, btn.dataset.filter);
        }
    });
});

async function fetchSuggestions(query) {
    if (!query || query.length < 2) {
        document.getElementById('search-suggestions')?.classList.add('hidden');
        return;
    }

    try {
        const data = await API.get(`/api/search/suggestions?q=${encodeURIComponent(query)}`);
        if (data && data.suggestions && data.suggestions.length > 0) {
            const blocked = [
                'trailer', 'teaser', 'review', 'reaction', 'full movie', 'movie review',
                'scenes', 'scene', 'comedy', 'status', 'whatsapp', 'interview', 'press meet',
                'box office', 'public talk', 'making', 'news', 'vlog', 'shorts', 'short'
            ];
            const cleaned = data.suggestions.filter(s => {
                const sLow = s.toLowerCase();
                return !blocked.some(b => sLow.includes(b));
            });
            if (cleaned.length > 0) {
                renderSuggestions(cleaned);
            } else {
                document.getElementById('search-suggestions')?.classList.add('hidden');
            }
        } else {
            document.getElementById('search-suggestions')?.classList.add('hidden');
        }
    } catch {
        document.getElementById('search-suggestions')?.classList.add('hidden');
    }
}

function renderSuggestions(suggestions) {
    const container = document.getElementById('search-suggestions');
    if (!container) return;

    container.innerHTML = suggestions.map(s => `
        <div class="suggestion-item" onclick="selectSuggestion('${escapeHtml(s)}')">
            <i data-lucide="search"></i>
            <span>${escapeHtml(s)}</span>
        </div>
    `).join('');
    container.classList.remove('hidden');
    lucide.createIcons({ nodes: [container] });
}

function selectSuggestion(query) {
    const input = document.getElementById('search-input');
    if (input) input.value = query;
    document.getElementById('search-clear')?.classList.remove('hidden');
    document.getElementById('search-suggestions')?.classList.add('hidden');
    performSearch(query);
}


// ============================================
// Page & State Restoration on Refresh / History Navigation
// ============================================

function restorePageState() {
    const hash = window.location.hash || '';
    let savedPage = 'home';
    try {
        savedPage = sessionStorage.getItem('wave_active_page') || 'home';
    } catch (e) {}

    if (hash.startsWith('#search') || (!hash && savedPage === 'search')) {
        let query = '';
        if (hash.includes('?q=')) {
            query = decodeURIComponent(hash.split('?q=')[1].split('&')[0] || '');
        }
        if (!query) {
            try {
                query = sessionStorage.getItem('wave_last_search_query') || '';
            } catch (e) {}
        }

        navigateTo('search', false);

        if (query) {
            const input = document.getElementById('search-input');
            if (input) input.value = query;
            document.getElementById('search-clear')?.classList.remove('hidden');
            document.getElementById('search-suggestions')?.classList.add('hidden');
            document.getElementById('search-browse-tags')?.classList.add('hidden');

            let renderedFromCache = false;
            try {
                const cached = sessionStorage.getItem('wave_last_search_results');
                if (cached) {
                    const parsed = JSON.parse(cached);
                    if (Array.isArray(parsed) && parsed.length > 0) {
                        AppState.searchResults = parsed;
                        AppState.lastSearchQuery = query;
                        document.getElementById('search-filter-tabs')?.classList.remove('hidden');
                        renderSearchResults(parsed, AppState.activeSearchFilter || 'all');
                        renderedFromCache = true;
                    }
                }
            } catch (e) {}

            if (!renderedFromCache) {
                performSearch(query, false);
            }
        }
    } else if (hash.startsWith('#library') || (!hash && savedPage === 'library')) {
        navigateTo('library', false);
    } else if (hash.startsWith('#extract') || (!hash && savedPage === 'extract')) {
        navigateTo('extract', false);
        if (typeof Extract !== 'undefined') {
            Extract.loadHistory();
        }
    } else if (hash.startsWith('#queue') || (!hash && savedPage === 'queue')) {
        navigateTo('queue', false);
    } else if (hash.startsWith('#artist')) {
        let artistName = '';
        if (hash.includes('?name=')) {
            artistName = decodeURIComponent(hash.split('?name=')[1].split('&')[0] || '');
        }
        if (!artistName && AppState.currentArtistName) {
            artistName = AppState.currentArtistName;
        }
        if (artistName) {
            openArtistPage(artistName);
        } else {
            navigateTo('home', false);
        }
    } else {
        navigateTo('home', false);
    }
}


// ============================================
// Track Card Rendering
// ============================================

function renderTrackCards(tracks, containerId) {
    const container = document.getElementById(containerId);
    if (!container) return;

    if (!tracks || tracks.length === 0) {
        container.innerHTML = `<div class="empty-state-card"><p>No songs available</p></div>`;
        return;
    }

    AppState.knownTracks = AppState.knownTracks || {};

    container.innerHTML = tracks.map((track, i) => {
        const meta = getTrackMetadata(track);
        const name = escapeHtml(meta.title);
        const sub = escapeHtml(meta.subtitle || meta.movie || meta.artist || '');
        const art = track.album_art || track.thumbnail || '';
        
        AppState.knownTracks[track.video_id] = {
            ...track,
            track_name: meta.title,
            movie: meta.movie,
            language: meta.language,
            subtitle: meta.subtitle
        };

        const isWaveOrUnknown = !meta.movie || meta.movie === 'Wave Music' || meta.movie === 'Unknown Artist';
        const subHtml = !isWaveOrUnknown
            ? `<div class="track-card-artist" onclick="event.stopPropagation(); searchForCategory('${escapeHtml(meta.movie)}')">${sub}</div>`
            : `<div class="track-card-artist" style="cursor: default; pointer-events: none;">${sub}</div>`;

        return `
            <div class="track-card" onclick="playSingleTrack('${track.video_id}')" title="${name}">
                <div class="track-card-art">
                    <img src="${art}" alt="" loading="lazy" onerror="this.style.display='none'">
                    <div class="track-card-play" onclick="event.stopPropagation(); playSingleTrack('${track.video_id}')" title="Play ${name}">
                        <i data-lucide="play"></i>
                    </div>
                </div>
                <div class="track-card-info">
                    <div class="track-card-title">${name}</div>
                    ${subHtml}
                </div>
            </div>
        `;
    }).join('');

    lucide.createIcons({ nodes: [container] });
}


// ============================================
// Playback Helpers from UI
// ============================================

function playSingleTrack(videoId, trackData = null) {
    const allKnown = [
        ...(AppState.searchResults || []),
        ...(AppState.currentArtist?.tracks || []),
        ...(AppState.recentlyPlayed || []),
    ];
    let track = trackData || AppState.knownTracks?.[videoId] || allKnown.find(t => t.video_id === videoId);
    if (!track) {
        track = {
            video_id: videoId,
            title: 'Playing...',
            artist: '',
            duration: 0,
            thumbnail: `https://i.ytimg.com/vi/${videoId}/hqdefault.jpg`,
        };
    }

    if (typeof Player !== 'undefined') {
        let queueList = [track];
        let queueIdx = 0;
        if (allKnown.length > 1) {
            const seen = new Set();
            const unique = [];
            for (const t of allKnown) {
                if (t && t.video_id && !seen.has(t.video_id)) {
                    seen.add(t.video_id);
                    unique.push(t);
                }
            }
            const foundIdx = unique.findIndex(t => t.video_id === videoId);
            if (foundIdx !== -1) {
                queueList = unique;
                queueIdx = foundIdx;
            }
        }
        Player.setQueue(queueList, queueIdx);
        Player.play(track);
    }
}

// Global alias for compatibility
window.playTrack = playSingleTrack;

function playTrackFromResults(index) {
    const track = AppState.searchResults[index];
    if (!track) return;

    if (typeof Player !== 'undefined') {
        Player.setQueue(AppState.searchResults, index);
        Player.play(track);
    }
}

function addToQueue(index) {
    const track = AppState.searchResults[index];
    if (!track) return;

    if (typeof Player !== 'undefined') {
        Player.addToQueue(track);
        showToast(`Added "${track.track_name || track.title}" to queue`);
    }
}

async function downloadSong(videoId, title, artist) {
    showToast(`Starting download: ${title}...`);
    try {
        const apiBase = (typeof API !== 'undefined' && API.baseUrl) ? API.baseUrl : '';
        const isExtracted = videoId && videoId.startsWith('ext_');
        const endpoint = isExtracted
            ? `${apiBase}/api/extract/download/${videoId}`
            : `${apiBase}/api/stream/${videoId}/download`;

        const link = document.createElement('a');
        link.href = `${endpoint}?title=${encodeURIComponent(title || 'song')}&artist=${encodeURIComponent(artist || 'artist')}`;
        link.download = `${title || 'song'}.mp3`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    } catch (e) {
        showToast('Download failed', 'error');
    }
}


// ============================================
// Utilities
// ============================================

function updateGreeting() {
    const hour = new Date().getHours();
    let greeting;
    if (hour < 12) greeting = 'Morning';
    else if (hour < 17) greeting = 'Afternoon';
    else greeting = 'Evening';

    const el = document.getElementById('greeting-time');
    if (el) el.textContent = greeting;
}

function escapeHtml(text) {
    if (!text) return '';
    return String(text)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function formatDuration(seconds) {
    if (!seconds || isNaN(seconds) || seconds <= 0) return '--:--';
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
}


// ============================================
// Initialization
// ============================================

document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.nav-item').forEach(item => {
        item.addEventListener('click', () => {
            navigateTo(item.dataset.page);
        });
    });

    const searchInput = document.getElementById('search-input');
    if (searchInput) {
        searchInput.addEventListener('input', (e) => {
            const query = e.target.value;
            document.getElementById('search-clear')?.classList.toggle('hidden', !query);

            clearTimeout(searchDebounceTimer);
            searchDebounceTimer = setTimeout(() => {
                fetchSuggestions(query);
            }, 250);
        });

        searchInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                document.getElementById('search-suggestions')?.classList.add('hidden');
                performSearch(searchInput.value);
            }
        });

        document.addEventListener('click', (e) => {
            if (!e.target.closest('.search-header')) {
                document.getElementById('search-suggestions')?.classList.add('hidden');
            }
        });
    }

    document.getElementById('search-clear')?.addEventListener('click', () => {
        const input = document.getElementById('search-input');
        if (input) {
            input.value = '';
            input.focus();
        }
        document.getElementById('search-clear')?.classList.add('hidden');
        document.getElementById('search-suggestions')?.classList.add('hidden');
        document.getElementById('search-browse-tags')?.classList.remove('hidden');
        document.getElementById('search-filter-tabs')?.classList.add('hidden');
        AppState.searchResults = [];
        AppState.lastSearchQuery = '';
        try {
            sessionStorage.removeItem('wave_last_search_query');
            sessionStorage.removeItem('wave_last_search_results');
        } catch (e) {}
        window.location.hash = '#search';
        document.getElementById('search-results').innerHTML = `
            <div class="search-placeholder">
                <i data-lucide="disc-3"></i>
                <h2>Explore songs worldwide</h2>
                <p>Type any song name, movie, singer, or genre in any language</p>
            </div>
        `;
        lucide.createIcons({ nodes: [document.getElementById('search-results')] });
    });

    // Keyboard shortcuts
    document.addEventListener('keydown', (e) => {
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

        switch (e.key) {
            case ' ':
                e.preventDefault();
                if (typeof Player !== 'undefined') Player.togglePlay();
                break;
            case 'ArrowRight':
                if (typeof Player !== 'undefined') Player.seekRelative(10);
                break;
            case 'ArrowLeft':
                if (typeof Player !== 'undefined') Player.seekRelative(-10);
                break;
            case 'ArrowUp':
                e.preventDefault();
                if (typeof Player !== 'undefined') Player.adjustVolume(5);
                break;
            case 'ArrowDown':
                e.preventDefault();
                if (typeof Player !== 'undefined') Player.adjustVolume(-5);
                break;
            case '/':
                e.preventDefault();
                navigateTo('search');
                break;
        }
    });

    initHomeFeed();

    if (typeof Auth !== 'undefined') {
        Auth.init();
    }

    if (typeof Extract !== 'undefined') {
        Extract.init();
    }

    // Restore page state on load and on history hash navigation
    window.addEventListener('hashchange', () => {
        if (isNavigatingProgrammatically) return;
        restorePageState();
    });
    restorePageState();

    // ============================================
    // Sidebar Resize
    // ============================================
    initSidebarResize();
});


// ============================================
// Sidebar Drag-to-Resize
// ============================================

function initSidebarResize() {
    const handle = document.getElementById('sidebar-resize-handle');
    const root = document.documentElement;
    if (!handle) return;

    // Restore saved width
    const saved = localStorage.getItem('wave_sidebar_width');
    if (saved) {
        const w = parseInt(saved, 10);
        if (w >= 160 && w <= 360) {
            root.style.setProperty('--sidebar-width', w + 'px');
        }
    }

    let isDragging = false;

    handle.addEventListener('mousedown', (e) => {
        e.preventDefault();
        isDragging = true;
        handle.classList.add('active');
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none';
    });

    document.addEventListener('mousemove', (e) => {
        if (!isDragging) return;
        let newWidth = e.clientX;
        newWidth = Math.max(160, Math.min(360, newWidth));
        root.style.setProperty('--sidebar-width', newWidth + 'px');
    });

    document.addEventListener('mouseup', () => {
        if (!isDragging) return;
        isDragging = false;
        handle.classList.remove('active');
        document.body.style.cursor = '';
        document.body.style.userSelect = '';

        const currentWidth = getComputedStyle(root).getPropertyValue('--sidebar-width').trim();
        localStorage.setItem('wave_sidebar_width', parseInt(currentWidth, 10));
    });

    // Touch support for mobile/tablet
    handle.addEventListener('touchstart', (e) => {
        isDragging = true;
        handle.classList.add('active');
    }, { passive: true });

    document.addEventListener('touchmove', (e) => {
        if (!isDragging) return;
        const touch = e.touches[0];
        let newWidth = touch.clientX;
        newWidth = Math.max(160, Math.min(360, newWidth));
        root.style.setProperty('--sidebar-width', newWidth + 'px');
    }, { passive: true });

    document.addEventListener('touchend', () => {
        if (!isDragging) return;
        isDragging = false;
        handle.classList.remove('active');

        const currentWidth = getComputedStyle(root).getPropertyValue('--sidebar-width').trim();
        localStorage.setItem('wave_sidebar_width', parseInt(currentWidth, 10));
    });
}
