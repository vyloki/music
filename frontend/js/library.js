/**
 * Wave — Library & Playlists Module
 * Manages user playlists, liked songs, listening history, and playlist detail view.
 */

const Library = {
    currentTab: 'liked',
    playlists: [],
    likedTracks: [],
    historyTracks: [],
    selectedTrackForPlaylist: null,
    currentPlaylistId: null,

    async init() {
        this.bindEvents();
        await this.loadPlaylistsNav();
    },

    bindEvents() {
        // Tab switching
        document.querySelectorAll('.library-tabs .tab').forEach(tab => {
            tab.addEventListener('click', () => {
                document.querySelectorAll('.library-tabs .tab').forEach(t => t.classList.remove('active'));
                tab.classList.add('active');
                this.currentTab = tab.dataset.tab;
                this.renderTabContent();
            });
        });

        // Open create playlist modal
        document.getElementById('btn-create-playlist')?.addEventListener('click', () => {
            this.openCreatePlaylistModal();
        });

        // Close playlist modal
        document.getElementById('btn-close-playlist-modal')?.addEventListener('click', () => {
            this.closeCreatePlaylistModal();
        });
        document.getElementById('btn-cancel-playlist')?.addEventListener('click', () => {
            this.closeCreatePlaylistModal();
        });

        // Submit create playlist
        document.getElementById('create-playlist-form')?.addEventListener('submit', (e) => {
            e.preventDefault();
            this.createPlaylist();
        });

        // Close add to playlist modal
        document.getElementById('btn-close-add-modal')?.addEventListener('click', () => {
            document.getElementById('add-to-playlist-modal')?.classList.add('hidden');
        });

        // Play playlist button
        document.getElementById('btn-play-playlist')?.addEventListener('click', () => {
            this.playCurrentPlaylist();
        });

        // Delete playlist button
        document.getElementById('btn-delete-playlist')?.addEventListener('click', () => {
            this.deleteCurrentPlaylist();
        });
    },

    // ============================================
    // Playlists in Sidebar
    // ============================================

    _loadPlaylistsPromise: null,
    _playlistsCacheTime: 0,

    async loadPlaylistsNav(force = false) {
        if (!AppState.isAuthenticated) return;

        const now = Date.now();
        if (!force && this.playlists && this.playlists.length > 0 && (now - this._playlistsCacheTime < 15000)) {
            this.renderPlaylistsNav();
            return;
        }

        if (this._loadPlaylistsPromise) {
            return this._loadPlaylistsPromise;
        }

        this._loadPlaylistsPromise = (async () => {
            try {
                const data = await API.get('/api/playlists');
                if (data && data.playlists) {
                    this.playlists = data.playlists;
                    this._playlistsCacheTime = Date.now();
                    this.renderPlaylistsNav();
                }
            } catch (e) {
                console.debug('Playlists load failed:', e);
            }
        })().finally(() => {
            this._loadPlaylistsPromise = null;
        });

        return this._loadPlaylistsPromise;
    },

    renderPlaylistsNav() {
        const container = document.getElementById('playlist-nav');
        if (!container) return;

        if (this.playlists.length === 0) {
            container.innerHTML = `<li style="opacity: 0.5; font-size: 12px; cursor: default;">No playlists yet</li>`;
            return;
        }

        container.innerHTML = this.playlists.map(p => `
            <li onclick="Library.viewPlaylist('${p.id}')">
                <i data-lucide="music-2"></i>
                <span>${escapeHtml(p.name)}</span>
            </li>
        `).join('');

        safeCreateIcons({ nodes: [container] });
    },

    // ============================================
    // Library Tabs Rendering
    // ============================================

    async renderTabContent() {
        const container = document.getElementById('library-content');
        if (!container) return;

        container.innerHTML = `
            <div class="loading-state">
                <div class="loader"><div class="loader-bar"></div><div class="loader-bar"></div><div class="loader-bar"></div></div>
                <p>Loading...</p>
            </div>
        `;

        if (this.currentTab === 'liked') {
            await this.renderLikedTab(container);
        } else if (this.currentTab === 'playlists') {
            await this.renderPlaylistsTab(container);
        } else if (this.currentTab === 'history') {
            await this.renderHistoryTab(container);
        } else if (this.currentTab === 'local') {
            if (typeof LocalLibrary !== 'undefined') {
                LocalLibrary.renderLocalTab();
            }
        }
    },

    async renderLikedTab(container) {
        let tracks = [];
        try {
            // 1. Try fetching from backend API
            const res = await API.get('/api/auth/liked');
            if (res && Array.isArray(res.tracks)) {
                tracks = res.tracks;
                try {
                    localStorage.setItem('wave_liked_tracks', JSON.stringify(tracks));
                } catch (e) {}
            }
        } catch (err) {
            // 2. Fallback to localStorage for guest or offline mode
            try {
                tracks = JSON.parse(localStorage.getItem('wave_liked_tracks') || '[]');
            } catch (e) {}
        }

        if (!tracks || tracks.length === 0) {
            try {
                tracks = JSON.parse(localStorage.getItem('wave_liked_tracks') || '[]');
            } catch (e) {}
        }

        this.likedTracks = tracks;

        if (!tracks || tracks.length === 0) {
            container.innerHTML = `<div class="empty-state"><i data-lucide="heart"></i><p>No liked songs yet. Click the heart icon on any song!</p></div>`;
        } else {
            container.innerHTML = `
                <div class="section-header-row">
                    <button class="btn btn-primary" onclick="Library.playAllLiked()"><i data-lucide="play"></i> Play All (${tracks.length})</button>
                </div>
                <div class="track-list">
                    ${tracks.map((track, i) => {
                        const meta = typeof getTrackMetadata === 'function' ? getTrackMetadata(track) : {
                            title: track.track_name || track.title || 'Unknown Song',
                            movie: track.movie || '',
                            language: track.language || '',
                            artist: track.artist || 'Unknown Artist',
                            subtitle: track.artist || 'Unknown Artist'
                        };
                        const name = escapeHtml(meta.title);
                        const movie = escapeHtml(meta.movie);
                        const language = escapeHtml(meta.language);
                        const artist = escapeHtml(meta.artist);

                        const subtitleHtml = meta.movie ? `
                            <span class="track-movie">${movie}</span>
                            ${language ? `<span class="track-lang-dot">•</span><span class="track-lang-text">${language}</span>` : ''}
                        ` : (meta.language ? `
                            <span class="track-movie">${artist}</span>
                            <span class="track-lang-dot">•</span><span class="track-lang-text">${language}</span>
                        ` : `
                            <span class="track-movie">${artist}</span>
                        `);

                        const safeTrackJson = JSON.stringify(track).replace(/"/g, '&quot;');

                        return `
                        <div class="track-row" onclick="Library.playLikedIndex(${i})">
                            <div class="track-row-art">
                                <img src="${track.thumbnail || track.album_art || ''}" alt="" onerror="this.style.display='none'">
                            </div>
                            <div class="track-row-info">
                                <div class="track-row-title">${name}</div>
                                <div class="track-row-artist">${subtitleHtml}</div>
                            </div>
                            <div class="track-row-duration">${formatDuration(track.duration)}</div>
                            <div class="track-row-actions">
                                <button class="btn-icon" onclick="event.stopPropagation(); downloadSong('${track.video_id}', '${name}', '${movie || artist}')" title="Download">
                                    <i data-lucide="download"></i>
                                </button>
                                <button class="btn-icon btn-like liked" onclick="event.stopPropagation(); Library.unlikeTrack('${track.video_id}')" title="Unlike">
                                    <i data-lucide="heart" style="fill: var(--color-error); color: var(--color-error);"></i>
                                </button>
                                <button class="btn-icon" onclick="event.stopPropagation(); Library.openAddToPlaylistModal('${track.video_id}', ${safeTrackJson})" title="Add to playlist">
                                    <i data-lucide="plus"></i>
                                </button>
                            </div>
                        </div>
                    `;}).join('')}
                </div>
            `;
        }
        safeCreateIcons({ nodes: [container] });
    },

    async renderPlaylistsTab(container) {
        await this.loadPlaylistsNav();

        container.innerHTML = `
            <div class="playlist-grid">
                <div class="playlist-card" onclick="Library.openCreatePlaylistModal()" style="border: 2px dashed var(--border-default); display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; min-height: 220px;">
                    <i data-lucide="plus-circle" style="width: 44px; height: 44px; color: var(--accent-dark); margin-bottom: 12px;"></i>
                    <h3 style="font-size: 15px; font-weight: 700;">Create Playlist</h3>
                    <p style="font-size: 12px; color: var(--text-tertiary); margin-top: 4px;">Custom mix of your favorites</p>
                </div>
                ${this.playlists.map(p => `
                    <div class="playlist-card" onclick="Library.viewPlaylist('${p.id}')">
                        <div class="playlist-card-cover">
                            ${p.cover_url ? `<img src="${p.cover_url}" alt="">` : `<i data-lucide="list-music"></i>`}
                        </div>
                        <div class="playlist-card-title">${escapeHtml(p.name)}</div>
                        <div class="playlist-card-count">${p.track_count} ${p.track_count === 1 ? 'song' : 'songs'}</div>
                    </div>
                `).join('')}
            </div>
        `;
        safeCreateIcons({ nodes: [container] });
    },

    playHistoryTrack(index) {
        if (this.historyTracks && this.historyTracks[index]) {
            const item = this.historyTracks[index];
            const meta = typeof getTrackMetadata === 'function' ? getTrackMetadata(item) : { title: item.title, artist: item.artist };
            if (typeof playSingleTrack === 'function') {
                playSingleTrack(item.video_id, {
                    video_id: item.video_id,
                    title: meta.title || item.title,
                    artist: meta.artist || item.artist,
                    thumbnail: item.thumbnail
                });
            }
        }
    },

    async renderHistoryTab(container) {
        try {
            const data = await API.get('/api/history?limit=40');
            if (data && data.history && data.history.length > 0) {
                this.historyTracks = data.history;
                container.innerHTML = `
                    <div class="section-header-row">
                        <span style="font-size: 13px; color: var(--text-tertiary);">${data.history.length} recently played songs</span>
                        <button class="btn btn-ghost" onclick="Library.clearHistory()"><i data-lucide="trash-2"></i> Clear History</button>
                    </div>
                    <div class="track-list">
                        ${data.history.map((item, i) => {
                            const meta = typeof getTrackMetadata === 'function' ? getTrackMetadata(item) : { title: item.title, movie: '', language: '', artist: item.artist, subtitle: item.artist };
                            const sub = meta.movie ? (meta.language ? `${meta.movie} • ${meta.language}` : meta.movie) : (meta.language ? `${meta.artist} • ${meta.language}` : meta.artist);
                            return `
                            <div class="track-row" onclick="Library.playHistoryTrack(${i})">
                                <div class="track-row-art">
                                    <img src="${item.thumbnail || ''}" alt="" onerror="this.style.display='none'">
                                </div>
                                <div class="track-row-info">
                                    <div class="track-row-title">${escapeHtml(meta.title)}</div>
                                    <div class="track-row-artist">${escapeHtml(sub)}</div>
                                </div>
                                <div class="track-row-duration">
                                    <button class="btn-icon" onclick="event.stopPropagation(); Library.playHistoryTrack(${i})" title="Play">
                                        <i data-lucide="play"></i>
                                    </button>
                                </div>
                            </div>
                        `;}).join('')}
                    </div>
                `;
            } else {
                container.innerHTML = `<div class="empty-state"><i data-lucide="clock"></i><p>Your listening history is empty</p></div>`;
            }
        } catch {
            container.innerHTML = `<div class="empty-state"><i data-lucide="clock"></i><p>Could not load history</p></div>`;
        }
        safeCreateIcons({ nodes: [container] });
    },

    // ============================================
    // Playlist Creation
    // ============================================

    openCreatePlaylistModal() {
        document.getElementById('playlist-name-input').value = '';
        document.getElementById('playlist-desc-input').value = '';
        document.getElementById('playlist-modal')?.classList.remove('hidden');
        document.getElementById('playlist-name-input')?.focus();
    },

    closeCreatePlaylistModal() {
        document.getElementById('playlist-modal')?.classList.add('hidden');
    },

    async createPlaylist() {
        const name = document.getElementById('playlist-name-input').value.trim();
        const description = document.getElementById('playlist-desc-input').value.trim();

        if (!name) return;

        try {
            const data = await API.post('/api/playlists', { name, description });
            this.closeCreatePlaylistModal();
            showToast(`Playlist "${name}" created!`, 'success');
            await this.loadPlaylistsNav();

            if (AppState.currentPage === 'library') {
                this.renderTabContent();
            }
        } catch (e) {
            showToast('Failed to create playlist', 'error');
        }
    },

    // ============================================
    // View Playlist Details
    // ============================================

    async viewPlaylist(playlistId) {
        this.currentPlaylistId = playlistId;
        navigateTo('playlist-detail');

        try {
            const data = await API.get(`/api/playlists/${playlistId}`);
            if (data) {
                document.getElementById('playlist-detail-title').textContent = data.name;
                document.getElementById('playlist-detail-desc').textContent = data.description || '';
                document.getElementById('playlist-detail-meta').textContent = `${data.track_count} ${data.track_count === 1 ? 'song' : 'songs'}`;

                const coverEl = document.getElementById('playlist-detail-cover');
                if (data.cover_url) {
                    coverEl.innerHTML = `<img src="${data.cover_url}" alt="">`;
                } else {
                    coverEl.innerHTML = `<i data-lucide="list-music"></i>`;
                }

                const listContainer = document.getElementById('playlist-track-list');
                if (data.tracks && data.tracks.length > 0) {
                    this.currentPlaylistTracks = data.tracks;
                    listContainer.innerHTML = `
                        <div class="track-list">
                            ${data.tracks.map((track, i) => {
                                const meta = typeof getTrackMetadata === 'function' ? getTrackMetadata(track) : { title: track.title, movie: '', language: '', artist: track.artist, subtitle: track.artist };
                                const sub = meta.movie ? (meta.language ? `${meta.movie} • ${meta.language}` : meta.movie) : (meta.language ? `${meta.artist} • ${meta.language}` : meta.artist);
                                return `
                                <div class="track-row" onclick="Library.playPlaylistIndex(${i})">
                                    <div class="track-row-art">
                                        <img src="${track.thumbnail || ''}" alt="" onerror="this.style.display='none'">
                                    </div>
                                    <div class="track-row-info">
                                        <div class="track-row-title">${escapeHtml(meta.title)}</div>
                                        <div class="track-row-artist">${escapeHtml(sub)}</div>
                                    </div>
                                    <div class="track-row-duration">${formatDuration(track.duration)}</div>
                                    <div class="track-row-actions">
                                        <button class="btn-icon" onclick="event.stopPropagation(); Library.removeTrackFromPlaylist('${playlistId}', '${track.video_id}')" title="Remove from playlist">
                                            <i data-lucide="trash"></i>
                                        </button>
                                    </div>
                                </div>
                            `;}).join('')}
                        </div>
                    `;
                } else {
                    this.currentPlaylistTracks = [];
                    listContainer.innerHTML = `<div class="empty-state"><i data-lucide="music"></i><p>This playlist is empty. Search for songs and click '+' to add them!</p></div>`;
                }

                safeCreateIcons({ nodes: [document.getElementById('page-playlist-detail')] });
            }
        } catch (e) {
            showToast('Failed to load playlist', 'error');
        }
    },

    playCurrentPlaylist() {
        if (this.currentPlaylistTracks && this.currentPlaylistTracks.length > 0) {
            Player.setQueue(this.currentPlaylistTracks, 0);
            Player.play(this.currentPlaylistTracks[0]);
        }
    },

    playPlaylistIndex(index) {
        if (this.currentPlaylistTracks && this.currentPlaylistTracks[index]) {
            Player.setQueue(this.currentPlaylistTracks, index);
            Player.play(this.currentPlaylistTracks[index]);
        }
    },

    async deleteCurrentPlaylist() {
        if (!confirm('Are you sure you want to delete this playlist?')) return;

        try {
            await API.delete(`/api/playlists/${this.currentPlaylistId}`);
            showToast('Playlist deleted', 'info');
            await this.loadPlaylistsNav();
            navigateTo('library');
        } catch {
            showToast('Failed to delete playlist', 'error');
        }
    },

    async removeTrackFromPlaylist(playlistId, videoId) {
        try {
            await API.delete(`/api/playlists/${playlistId}/tracks/${videoId}`);
            showToast('Song removed', 'info');
            this.viewPlaylist(playlistId);
        } catch {
            showToast('Failed to remove song', 'error');
        }
    },

    // ============================================
    // Add Track to Playlist Modal
    // ============================================

    async openAddToPlaylistModal(videoId, trackData) {
        this.selectedTrackForPlaylist = trackData || { video_id: videoId };

        const modal = document.getElementById('add-to-playlist-modal');
        const listContainer = document.getElementById('add-playlist-list');

        modal.classList.remove('hidden');
        listContainer.innerHTML = `<div class="loading-state"><p>Loading playlists...</p></div>`;

        await this.loadPlaylistsNav();

        if (this.playlists.length === 0) {
            listContainer.innerHTML = `
                <div class="empty-state">
                    <p>No playlists found.</p>
                    <button class="btn btn-primary" onclick="Library.closeAddToModalAndCreate()">Create New Playlist</button>
                </div>
            `;
            return;
        }

        listContainer.innerHTML = this.playlists.map(p => `
            <div class="add-playlist-item" onclick="Library.addSelectedTrackTo('${p.id}', '${escapeHtml(p.name)}')">
                <div style="font-weight: 600; font-size: 14px;">${escapeHtml(p.name)}</div>
                <div style="font-size: 12px; color: var(--text-tertiary);">${p.track_count} songs</div>
            </div>
        `).join('');
    },

    closeAddToModalAndCreate() {
        document.getElementById('add-to-playlist-modal')?.classList.add('hidden');
        this.openCreatePlaylistModal();
    },

    async addSelectedTrackTo(playlistId, playlistName) {
        if (!this.selectedTrackForPlaylist) return;

        const track = this.selectedTrackForPlaylist;
        try {
            await API.post(`/api/playlists/${playlistId}/tracks`, {
                video_id: track.video_id,
                title: track.track_name || track.title || 'Unknown',
                artist: track.artist || 'Unknown',
                duration: track.duration || 0,
                thumbnail: track.thumbnail || track.album_art || '',
            });

            document.getElementById('add-to-playlist-modal')?.classList.add('hidden');
            showToast(`Added to "${playlistName}"`, 'success');
            await this.loadPlaylistsNav();
        } catch {
            showToast('Failed to add to playlist', 'error');
        }
    },

    // ============================================
    // Liked Songs Helpers
    // ============================================

    playAllLiked() {
        if (this.likedTracks && this.likedTracks.length > 0) {
            Player.setQueue(this.likedTracks, 0);
            Player.play(this.likedTracks[0]);
        }
    },

    playLikedIndex(index) {
        if (this.likedTracks && this.likedTracks[index]) {
            Player.setQueue(this.likedTracks, index);
            Player.play(this.likedTracks[index]);
        }
    },

    async toggleLike(videoId, track = null) {
        if (!videoId) return false;

        let isNowLiked = false;
        const currentTrack = track || (typeof Player !== 'undefined' && Player.currentTrack?.video_id === videoId ? Player.currentTrack : { video_id: videoId });

        try {
            // Send API request to persist in DB
            const res = await API.post(`/api/auth/like/${videoId}`, { track: currentTrack });
            if (res && typeof res.is_liked === 'boolean') {
                isNowLiked = res.is_liked;
            } else if (res && res.message) {
                isNowLiked = res.message.toLowerCase().includes('liked') && !res.message.toLowerCase().includes('unliked');
            }
        } catch (err) {
            // Guest / Offline fallback toggle
            let localLiked = [];
            try {
                localLiked = JSON.parse(localStorage.getItem('wave_liked_tracks') || '[]');
            } catch (e) {}

            const existingIdx = localLiked.findIndex(t => t.video_id === videoId);
            if (existingIdx >= 0) {
                localLiked.splice(existingIdx, 1);
                isNowLiked = false;
            } else {
                localLiked.unshift(currentTrack);
                isNowLiked = true;
            }
            localStorage.setItem('wave_liked_tracks', JSON.stringify(localLiked));
        }

        // Sync local storage cache
        try {
            let localLiked = JSON.parse(localStorage.getItem('wave_liked_tracks') || '[]');
            const existingIdx = localLiked.findIndex(t => t.video_id === videoId);
            if (isNowLiked) {
                if (existingIdx < 0) localLiked.unshift(currentTrack);
            } else {
                if (existingIdx >= 0) localLiked.splice(existingIdx, 1);
            }
            localStorage.setItem('wave_liked_tracks', JSON.stringify(localLiked));
        } catch (e) {}

        // Update UI everywhere
        this.updateLikeUI(videoId, isNowLiked);

        showToast(isNowLiked ? 'Added to Liked Songs' : 'Removed from Liked Songs', 'success');

        // If currently on Liked tab in Library, refresh tab immediately
        if (AppState.currentPage === 'library' && this.currentTab === 'liked') {
            const container = document.getElementById('library-content');
            if (container) this.renderLikedTab(container);
        }

        return isNowLiked;
    },

    isLiked(videoId) {
        if (!videoId) return false;
        try {
            const localLiked = JSON.parse(localStorage.getItem('wave_liked_tracks') || '[]');
            if (localLiked.some(t => t.video_id === videoId)) return true;
        } catch (e) {}
        if (AppState.user?.liked_tracks?.includes(videoId)) return true;
        return false;
    },

    updateLikeUI(videoId, isLiked) {
        // 1. Player bar heart
        if (typeof Player !== 'undefined' && Player.currentTrack && Player.currentTrack.video_id === videoId) {
            const playerLikeBtn = Player.elements?.likeBtn || document.getElementById('btn-like');
            if (playerLikeBtn) {
                playerLikeBtn.classList.toggle('liked', isLiked);
                const icon = playerLikeBtn.querySelector('i');
                if (icon) {
                    if (isLiked) {
                        icon.setAttribute('fill', 'var(--color-error)');
                        icon.style.fill = 'var(--color-error)';
                        icon.style.color = 'var(--color-error)';
                    } else {
                        icon.removeAttribute('fill');
                        icon.style.fill = 'none';
                        icon.style.color = '';
                    }
                }
            }
        }

        // 2. Extract page like button
        const extractLikeBtn = document.getElementById('btn-extract-like');
        if (extractLikeBtn && typeof Extract !== 'undefined' && Extract.currentExtractedTrack?.video_id === videoId) {
            extractLikeBtn.classList.toggle('liked', isLiked);
            extractLikeBtn.innerHTML = isLiked
                ? `<i data-lucide="heart" style="fill: var(--color-error); color: var(--color-error);"></i> Liked`
                : `<i data-lucide="heart"></i> Like`;
            safeCreateIcons({ nodes: [extractLikeBtn] });
        }
    },

    async unlikeTrack(videoId) {
        await this.toggleLike(videoId);
    },

    async clearHistory() {
        if (!confirm('Clear your entire listening history?')) return;
        try {
            await API.delete('/api/history');
            showToast('History cleared', 'info');
            this.renderTabContent();
        } catch {
            showToast('Failed to clear history', 'error');
        }
    }
};

window.Library = Library;

document.addEventListener('DOMContentLoaded', () => {
    Library.init();
});
