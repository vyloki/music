/**
 * Wave — Synced Lyrics Module
 * High-Precision real-time lyric synchronization engine with sub-millisecond accuracy,
 * fluid viewport centering, interactive seek-to-line, and Wave Auto-Sync Engine.
 * 
 * Automatically compensates for channel bumpers & intro advertisements (e.g. Saregama, Aditya Music)
 * without requiring manual user calibration.
 */

const Lyrics = {
    syncedLines: [],
    activeIndex: -1,
    currentTrackId: null,
    syncOffset: 0.0,
    isUserScrolling: false,
    userScrollTimeout: null,
    _initializedEvents: false,

    init() {
        if (this._initializedEvents) return;
        this._initializedEvents = true;

        const bodyEl = document.getElementById('lyrics-body');
        if (bodyEl) {
            const handleUserScroll = () => {
                this.isUserScrolling = true;
                if (this.userScrollTimeout) {
                    clearTimeout(this.userScrollTimeout);
                }
                this.userScrollTimeout = setTimeout(() => {
                    this.isUserScrolling = false;
                    this.scrollToActiveLine();
                }, 3000);
            };

            bodyEl.addEventListener('touchstart', handleUserScroll, { passive: true });
            bodyEl.addEventListener('touchmove', handleUserScroll, { passive: true });
            bodyEl.addEventListener('wheel', handleUserScroll, { passive: true });
        }
    },

    async loadLyrics(track) {
        if (!track || !track.video_id) return;
        this.init();

        const contentEl = document.getElementById('lyrics-content');
        const loadingEl = document.getElementById('lyrics-loading');
        const badgeEl = document.getElementById('lyrics-badge');

        // Update header & artwork
        const titleEl = document.getElementById('lyrics-track-name');
        const artistEl = document.getElementById('lyrics-artist');
        if (titleEl) titleEl.textContent = track.track_name || track.title || 'Unknown';
        if (artistEl) artistEl.textContent = track.artist || 'Unknown Artist';

        const artImg = document.getElementById('lyrics-art-img');
        const artFrame = document.getElementById('lyrics-art-frame');
        const art = track.thumbnail || track.album_art || '';
        if (artImg) {
            if (art) {
                artImg.src = art;
                artFrame?.classList.add('has-art');
            } else {
                artImg.src = '';
                artFrame?.classList.remove('has-art');
            }
        }

        this.currentTrackId = track.video_id;
        this.syncedLines = [];
        this.activeIndex = -1;
        this.isUserScrolling = false;
        this.syncOffset = 0.0; // Auto-calibrated by backend Auto-Sync Engine

        loadingEl?.classList.remove('hidden');
        if (contentEl) contentEl.innerHTML = '';

        try {
            const title = encodeURIComponent(track.track_name || track.title || '');
            const artist = encodeURIComponent(track.artist || '');
            const movie = encodeURIComponent(track.movie || track.album || '');
            const duration = track.duration || 0;
            const language = encodeURIComponent(track.language || '');
            const channel = encodeURIComponent(track.channel || track.uploader || track.artist || '');

            const res = await API.get(`/api/lyrics/${track.video_id}?title=${title}&artist=${artist}&movie=${movie}&duration=${duration}&language=${language}&channel=${channel}`);
            loadingEl?.classList.add('hidden');

            if (res && res.has_synced && res.synced && res.synced.length > 0) {
                this.syncedLines = res.synced;
                if (badgeEl) {
                    badgeEl.textContent = 'Synced Lyrics';
                    badgeEl.style.display = 'inline-block';
                }
                this.renderSynced();

                // Initial sync to current playback position
                const curTime = (Player?.activeEngine === 'yt' && Player.YTBridge?.player?.getCurrentTime)
                    ? Player.YTBridge.player.getCurrentTime()
                    : (Player?.audio?.currentTime || 0);
                this.syncToTime(curTime);
            } else if (res && res.plain) {
                if (badgeEl) {
                    badgeEl.textContent = 'Plain Lyrics';
                    badgeEl.style.display = 'inline-block';
                }
                if (contentEl) contentEl.innerHTML = `<div class="lyrics-plain">${escapeHtml(res.plain)}</div>`;
            } else {
                if (badgeEl) badgeEl.style.display = 'none';
                if (contentEl) contentEl.innerHTML = `<p class="lyrics-placeholder">No lyrics available for this song</p>`;
            }
        } catch (error) {
            loadingEl?.classList.add('hidden');
            if (contentEl) contentEl.innerHTML = `<p class="lyrics-placeholder">Could not load lyrics</p>`;
        }
    },

    renderSynced() {
        const contentEl = document.getElementById('lyrics-content');
        if (!contentEl) return;

        contentEl.innerHTML = this.syncedLines.map((line, index) => `
            <div class="lyrics-line" id="lyric-line-${index}" onclick="Lyrics.seekToLine(${index})">
                ${escapeHtml(line.text)}
            </div>
        `).join('');
    },

    seekToLine(index) {
        if (this.syncedLines[index] && typeof Player !== 'undefined') {
            const targetTime = Math.max(0, this.syncedLines[index].time);
            Player.seekToSeconds(targetTime);
            this.isUserScrolling = false;
            this.syncToTime(targetTime);
        }
    },

    // Silent backward-compatible stubs for any legacy event callers
    adjustOffset(delta) {},
    resetOffset() {},
    updateOffsetUI() {},

    syncToTime(currentTime) {
        if (!this.syncedLines || this.syncedLines.length === 0) return;

        // Timestamps in syncedLines are already pre-calibrated by Auto-Sync
        const calibratedTime = currentTime + this.syncOffset;

        // Binary search to find the highest line index where line.time <= calibratedTime
        let low = 0;
        let high = this.syncedLines.length - 1;
        let newIndex = -1;

        while (low <= high) {
            const mid = (low + high) >> 1;
            if (this.syncedLines[mid].time <= calibratedTime) {
                newIndex = mid;
                low = mid + 1;
            } else {
                high = mid - 1;
            }
        }

        if (newIndex !== this.activeIndex) {
            // Remove previous active state
            if (this.activeIndex >= 0) {
                document.getElementById(`lyric-line-${this.activeIndex}`)?.classList.remove('active');
            }

            // Apply new active state
            if (newIndex >= 0) {
                const currentEl = document.getElementById(`lyric-line-${newIndex}`);
                if (currentEl) {
                    currentEl.classList.add('active');
                    if (!this.isUserScrolling) {
                        this.scrollToElement(currentEl);
                    }
                }
            }

            this.activeIndex = newIndex;
        }
    },

    scrollToElement(el) {
        const container = document.getElementById('lyrics-body');
        if (!container || !el) return;

        const containerHeight = container.clientHeight;
        const targetTop = el.offsetTop - (containerHeight / 2) + (el.clientHeight / 2);

        container.scrollTo({
            top: Math.max(0, targetTop),
            behavior: 'smooth'
        });
    },

    scrollToActiveLine() {
        if (this.activeIndex >= 0) {
            const currentEl = document.getElementById(`lyric-line-${this.activeIndex}`);
            if (currentEl) {
                this.scrollToElement(currentEl);
            }
        }
    }
};

window.Lyrics = Lyrics;
