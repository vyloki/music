/**
 * Wave — Link Audio Extractor
 * Handles audio extraction from YouTube, Instagram, Twitter/X, TikTok, Reddit, etc.
 * Supports 'Same Audio' (exact duration) and 'Original Song' (full-length matching).
 */

const Extract = {
    currentExtractedTrack: null,
    selectedMode: 'same', // 'same' or 'original'

    init() {
        this.bindEvents();
        this.loadHistory();
    },

    bindEvents() {
        const urlInput = document.getElementById('extract-url-input');
        const clearBtn = document.getElementById('btn-extract-clear');
        const pasteBtn = document.getElementById('btn-extract-paste');
        const submitBtn = document.getElementById('btn-extract-submit');
        const clearHistoryBtn = document.getElementById('btn-clear-extract-history');

        // Mode cards toggle
        const modeCardSame = document.getElementById('mode-card-same');
        const modeCardOriginal = document.getElementById('mode-card-original');

        if (modeCardSame && modeCardOriginal) {
            modeCardSame.addEventListener('click', () => {
                this.selectedMode = 'same';
                modeCardSame.classList.add('active');
                modeCardOriginal.classList.remove('active');
                const radio = modeCardSame.querySelector('input[type="radio"]');
                if (radio) radio.checked = true;
            });

            modeCardOriginal.addEventListener('click', () => {
                this.selectedMode = 'original';
                modeCardOriginal.classList.add('active');
                modeCardSame.classList.remove('active');
                const radio = modeCardOriginal.querySelector('input[type="radio"]');
                if (radio) radio.checked = true;
            });
        }

        // URL Input changes
        if (urlInput) {
            urlInput.addEventListener('input', () => {
                if (urlInput.value.trim()) {
                    clearBtn?.classList.remove('hidden');
                } else {
                    clearBtn?.classList.add('hidden');
                }
            });

            urlInput.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    this.handleExtract();
                }
            });
        }

        // Clear button
        if (clearBtn && urlInput) {
            clearBtn.addEventListener('click', () => {
                urlInput.value = '';
                clearBtn.classList.add('hidden');
                urlInput.focus();
            });
        }

        // Paste button
        if (pasteBtn && urlInput) {
            pasteBtn.addEventListener('click', async () => {
                try {
                    const text = await navigator.clipboard.readText();
                    if (text) {
                        urlInput.value = text.trim();
                        clearBtn?.classList.remove('hidden');
                        showToast('Link pasted from clipboard', 'info');
                    }
                } catch (err) {
                    showToast('Please allow clipboard permissions or paste manually', 'warning');
                }
            });
        }

        // Submit Extract button
        if (submitBtn) {
            submitBtn.addEventListener('click', () => this.handleExtract());
        }

        // Clear history button
        if (clearHistoryBtn) {
            clearHistoryBtn.addEventListener('click', () => this.clearHistory());
        }
    },

    async handleExtract() {
        const urlInput = document.getElementById('extract-url-input');
        const loadingEl = document.getElementById('extract-loading');
        const loadingText = document.getElementById('extract-loading-text');
        const errorEl = document.getElementById('extract-error');
        const errorMsg = document.getElementById('extract-error-msg');
        const resultEl = document.getElementById('extract-result');
        const submitBtn = document.getElementById('btn-extract-submit');

        const url = urlInput ? urlInput.value.trim() : '';
        if (!url) {
            showToast('Please paste or enter a URL first', 'warning');
            urlInput?.focus();
            return;
        }

        // Reset display states
        errorEl?.classList.add('hidden');
        resultEl?.classList.add('hidden');
        loadingEl?.classList.remove('hidden');
        if (submitBtn) submitBtn.disabled = true;

        if (loadingText) {
            loadingText.textContent = this.selectedMode === 'original'
                ? 'Extracting and searching for the full original song...'
                : 'Extracting exact audio from link...';
        }

        try {
            const data = await API.post('/api/extract', {
                url: url,
                mode: this.selectedMode
            });

            loadingEl?.classList.add('hidden');
            if (submitBtn) submitBtn.disabled = false;

            if (data && data.success && data.track) {
                this.currentExtractedTrack = data.track;
                this.renderResult(data.track, data.mode, data.platform);
                showToast(
                    data.mode === 'original' && data.track.matched_original
                        ? 'Found original full-length song!'
                        : 'Audio extracted successfully!',
                    'success'
                );
                this.loadHistory();
            } else {
                throw new Error(data?.error || 'Could not extract audio from this link.');
            }
        } catch (err) {
            loadingEl?.classList.add('hidden');
            if (submitBtn) submitBtn.disabled = false;

            if (errorEl && errorMsg) {
                errorMsg.textContent = err.message || 'Could not extract audio from this link. Make sure the link is public and accessible.';
                errorEl.classList.remove('hidden');
                lucide.createIcons({ nodes: [errorEl] });
            }
            showToast('Extraction failed. Please check the link.', 'error');
        }
    },

    renderResult(track, mode, platform) {
        const resultContainer = document.getElementById('extract-result');
        if (!resultContainer) return;

        const title = escapeHtml(track.title || track.track_name || 'Extracted Song');
        const artist = escapeHtml(track.artist || 'Unknown Artist');
        const movie = escapeHtml(track.movie || '');
        const language = escapeHtml(track.language || '');
        const durationStr = formatDuration(track.duration || 0);
        const platformName = escapeHtml(platform || track.platform || 'Web Link');

        const subtitle = movie
            ? `${movie}${language ? ` • ${language}` : ''}`
            : `${artist}${language ? ` • ${language}` : ''}`;

        const modeBadge = mode === 'original' && track.matched_original
            ? '<span class="extract-platform-tag"><i data-lucide="disc-3"></i> Full Original Song</span>'
            : '<span class="extract-platform-tag"><i data-lucide="scissors"></i> Extracted Clip</span>';

        const safeTrackJson = JSON.stringify(track).replace(/"/g, '&quot;');

        const isLiked = typeof Library !== 'undefined' ? Library.isLiked(track.video_id) : false;

        resultContainer.innerHTML = `
            <div class="extract-result-card">
                <div class="extract-result-art">
                    <img src="${track.thumbnail || track.album_art || ''}"
                         alt="${title}"
                         loading="lazy"
                         onerror="this.src='https://images.unsplash.com/photo-1511671782779-c97d3d27a1d4?w=500&auto=format&fit=crop&q=60'">
                </div>
                <div class="extract-result-details">
                    <div class="extract-badge-row">
                        <span class="extract-platform-tag"><i data-lucide="link"></i> ${platformName}</span>
                        ${modeBadge}
                    </div>
                    <div class="extract-result-title">${title}</div>
                    <div class="extract-result-subtitle">${subtitle} • ${durationStr}</div>

                    <div class="extract-result-actions">
                        <button class="btn btn-primary" id="btn-extract-play">
                            <i data-lucide="play"></i> Play Now
                        </button>
                        <button class="btn btn-secondary" id="btn-extract-download">
                            <i data-lucide="download"></i> Download MP3
                        </button>
                        <button class="btn btn-secondary" id="btn-extract-playlist">
                            <i data-lucide="plus"></i> Add to Playlist
                        </button>
                        <button class="btn btn-secondary btn-like ${isLiked ? 'liked' : ''}" id="btn-extract-like">
                            <i data-lucide="heart" ${isLiked ? 'style="fill: var(--color-error); color: var(--color-error);"' : ''}></i>
                            <span id="extract-like-text">${isLiked ? 'Liked' : 'Like'}</span>
                        </button>
                        <button class="btn btn-secondary" id="btn-extract-queue">
                            <i data-lucide="list-plus"></i> Add to Queue
                        </button>
                    </div>
                </div>
            </div>
        `;

        resultContainer.classList.remove('hidden');
        lucide.createIcons({ nodes: [resultContainer] });

        // Bind Action Buttons
        document.getElementById('btn-extract-play')?.addEventListener('click', () => {
            this.playTrack(track);
        });

        document.getElementById('btn-extract-download')?.addEventListener('click', () => {
            this.downloadTrack(track);
        });

        document.getElementById('btn-extract-playlist')?.addEventListener('click', () => {
            if (typeof Library !== 'undefined') {
                Library.openAddToPlaylistModal(track.video_id, track);
            }
        });

        document.getElementById('btn-extract-like')?.addEventListener('click', async () => {
            if (typeof Library !== 'undefined') {
                const nowLiked = await Library.toggleLike(track.video_id, track);
                const btn = document.getElementById('btn-extract-like');
                const textEl = document.getElementById('extract-like-text');
                if (btn) {
                    btn.classList.toggle('liked', nowLiked);
                    if (textEl) textEl.textContent = nowLiked ? 'Liked' : 'Like';
                    const icon = btn.querySelector('i');
                    if (icon) {
                        if (nowLiked) {
                            icon.style.fill = 'var(--color-error)';
                            icon.style.color = 'var(--color-error)';
                        } else {
                            icon.style.fill = 'none';
                            icon.style.color = '';
                        }
                    }
                    lucide.createIcons({ nodes: [btn] });
                }
            }
        });

        document.getElementById('btn-extract-queue')?.addEventListener('click', () => {
            if (typeof Player !== 'undefined') {
                Player.addToQueue(track);
                showToast(`Added "${title}" to queue`);
            }
        });
    },

    playTrack(track) {
        if (!track) return;
        if (typeof Player !== 'undefined') {
            Player.setQueue([track], 0);
            Player.play(track);
            showToast(`Playing: ${track.track_name || track.title}`, 'info');
        }
    },

    downloadTrack(track) {
        if (!track) return;
        const title = track.title || track.track_name || 'extracted_song';
        const artist = track.movie || track.artist || 'artist';

        const apiBase = (typeof API !== 'undefined' && API.baseUrl) ? API.baseUrl : '';
        const downloadUrl = track.video_id && track.video_id.startsWith('ext_')
            ? `${apiBase}/api/extract/download/${track.video_id}?title=${encodeURIComponent(title)}&artist=${encodeURIComponent(artist)}`
            : `${apiBase}/api/stream/${track.video_id}/download?title=${encodeURIComponent(title)}&artist=${encodeURIComponent(artist)}`;

        showToast(`Starting download: ${title}...`, 'info');
        const link = document.createElement('a');
        link.href = downloadUrl;
        link.download = `${title}.mp3`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    },

    async loadHistory() {
        const container = document.getElementById('extract-history-list');
        if (!container) return;

        let historyItems = [];

        // 1. Try local storage first
        try {
            const raw = localStorage.getItem('wave_extract_history');
            if (raw) historyItems = JSON.parse(raw);
        } catch (e) {}

        // 2. Fetch from backend API
        try {
            const data = await API.get('/api/extract/history?limit=15');
            if (data && Array.isArray(data.history) && data.history.length > 0) {
                historyItems = data.history;
                localStorage.setItem('wave_extract_history', JSON.stringify(historyItems));
            }
        } catch (e) {}

        if (historyItems.length === 0) {
            container.innerHTML = `
                <div class="empty-state" style="padding: 24px 0;">
                    <i data-lucide="link"></i>
                    <p>No links extracted yet. Paste a link above to begin.</p>
                </div>
            `;
            lucide.createIcons({ nodes: [container] });
            return;
        }

        container.innerHTML = historyItems.map((item, index) => {
            const track = item.track || {
                video_id: item.url,
                title: item.title,
                track_name: item.title,
                artist: item.artist,
                movie: item.movie,
                language: item.language,
                thumbnail: item.thumbnail,
                duration: item.duration,
                platform: item.platform,
            };

            const title = escapeHtml(item.title || 'Extracted Track');
            const artist = escapeHtml(item.artist || 'Unknown Artist');
            const movie = escapeHtml(item.movie || '');
            const language = escapeHtml(item.language || '');
            const durationStr = formatDuration(item.duration || 0);
            const platform = escapeHtml(item.platform || 'Web Link');

            const subtitleHtml = movie
                ? `<span class="track-movie">${movie}</span>${language ? `<span class="track-lang-dot">•</span><span class="track-lang-text">${language}</span>` : ''}`
                : `<span class="track-movie">${artist}</span>${language ? `<span class="track-lang-dot">•</span><span class="track-lang-text">${language}</span>` : ''}`;

            const safeTrackJson = JSON.stringify(track).replace(/"/g, '&quot;');

            return `
                <div class="extract-history-item" onclick="Extract.playTrack(Extract.getHistoryTrack(${index}))">
                    <div class="track-row-art">
                        <img src="${item.thumbnail || ''}" alt="" loading="lazy" onerror="this.style.display='none'">
                    </div>
                    <div class="track-row-info">
                        <div class="track-row-title">
                            <span>${title}</span>
                            <span class="extract-platform-tag">${platform}</span>
                        </div>
                        <div class="track-row-artist">${subtitleHtml}</div>
                    </div>
                    <div class="track-row-duration">${durationStr}</div>
                    <div class="track-row-actions">
                        <button class="btn-icon" onclick="event.stopPropagation(); Extract.downloadTrack(Extract.getHistoryTrack(${index}))" title="Download">
                            <i data-lucide="download"></i>
                        </button>
                        <button class="btn-icon btn-like ${typeof Library !== 'undefined' && Library.isLiked(track.video_id) ? 'liked' : ''}"
                                onclick="event.stopPropagation(); Library.toggleLike('${track.video_id}', ${safeTrackJson})"
                                title="Like">
                            <i data-lucide="heart" ${typeof Library !== 'undefined' && Library.isLiked(track.video_id) ? 'style="fill: var(--color-error); color: var(--color-error);"' : ''}></i>
                        </button>
                        <button class="btn-icon" onclick="event.stopPropagation(); Library.openAddToPlaylistModal('${track.video_id}', ${safeTrackJson})" title="Add to playlist">
                            <i data-lucide="plus"></i>
                        </button>
                        <button class="btn-icon" onclick="event.stopPropagation(); Extract.deleteHistoryItem('${item.id || index}')" title="Delete from history">
                            <i data-lucide="trash-2"></i>
                        </button>
                    </div>
                </div>
            `;
        }).join('');

        this._historyCache = historyItems;
        lucide.createIcons({ nodes: [container] });
    },

    getHistoryTrack(index) {
        if (this._historyCache && this._historyCache[index]) {
            return this._historyCache[index].track || this._historyCache[index];
        }
        return null;
    },

    async deleteHistoryItem(id) {
        try {
            await API.delete(`/api/extract/history/${id}`);
        } catch (e) {}

        try {
            let list = JSON.parse(localStorage.getItem('wave_extract_history') || '[]');
            list = list.filter((item, idx) => item.id !== id && String(idx) !== String(id));
            localStorage.setItem('wave_extract_history', JSON.stringify(list));
        } catch (e) {}

        this.loadHistory();
        showToast('Item removed from extraction history', 'info');
    },

    async clearHistory() {
        try {
            await API.delete('/api/extract/history');
        } catch (e) {}

        try {
            localStorage.removeItem('wave_extract_history');
        } catch (e) {}

        this.loadHistory();
        showToast('Extraction history cleared', 'info');
    }
};

window.Extract = Extract;
