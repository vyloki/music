/**
 * YouTube Audio Bridge
 * Client-side embedded playback engine to bypass cloud IP data center rate-limits.
 */
console.info('Wave Player v10.0: Next/Prev track active, 10s skip removed');
const YTBridge = {
    player: null,
    isReady: false,
    active: false,
    pollTimer: null,
    pendingId: null,

    init() {
        if (window.YT && window.YT.Player) {
            this.createPlayer();
            return;
        }
        if (!document.getElementById('yt-iframe-api-script')) {
            const tag = document.createElement('script');
            tag.id = 'yt-iframe-api-script';
            tag.src = 'https://www.youtube.com/iframe_api';
            document.head.appendChild(tag);
        }
        window.onYouTubeIframeAPIReady = () => {
            this.createPlayer();
        };
    },

    createPlayer() {
        if (this.player) return;
        let host = document.getElementById('yt-bridge-host');
        if (!host) {
            host = document.createElement('div');
            host.id = 'yt-bridge-host';
            host.style.cssText = 'position:fixed;bottom:-9999px;left:-9999px;width:1px;height:1px;opacity:0;pointer-events:none;z-index:-999;';
            document.body.appendChild(host);
        }
        const inner = document.createElement('div');
        inner.id = 'yt-bridge-iframe-target';
        host.appendChild(inner);

        try {
            this.player = new YT.Player('yt-bridge-iframe-target', {
                height: '1',
                width: '1',
                playerVars: {
                    autoplay: 1,
                    controls: 0,
                    disablekb: 1,
                    fs: 0,
                    playsinline: 1,
                    rel: 0,
                    modestbranding: 1,
                },
                events: {
                    onReady: () => {
                        this.isReady = true;
                        if (this.pendingId) {
                            this.play(this.pendingId);
                            this.pendingId = null;
                        }
                    },
                    onStateChange: (e) => {
                        this.handleState(e.data);
                    },
                    onError: (e) => {
                        console.warn('YTBridge playback code:', e.data);
                    }
                }
            });
        } catch (e) {
            console.warn('YTBridge creation error:', e);
        }
    },

    play(videoId) {
        this.active = true;
        if (!this.isReady || !this.player || !this.player.loadVideoById) {
            this.pendingId = videoId;
            return;
        }
        try {
            this.player.loadVideoById(videoId);
            this.player.playVideo();
            if (this.player.setVolume) {
                this.player.setVolume(Player.volume);
            }
            this.startPolling();
        } catch (e) {
            console.warn('YTBridge play error:', e);
        }
    },

    pause() {
        if (this.player && this.player.pauseVideo) {
            try { this.player.pauseVideo(); } catch (e) {}
        }
        this.stopPolling();
    },

    resume() {
        if (this.player && this.player.playVideo) {
            try {
                this.player.playVideo();
                this.startPolling();
            } catch (e) {}
        }
    },

    seekTo(seconds) {
        if (this.player && this.player.seekTo) {
            try { this.player.seekTo(seconds, true); } catch (e) {}
        }
    },

    setVolume(vol) {
        if (this.player && this.player.setVolume) {
            try { this.player.setVolume(vol); } catch (e) {}
        }
    },

    stop() {
        this.active = false;
        this.stopPolling();
        if (this.player && this.player.stopVideo) {
            try { this.player.stopVideo(); } catch (e) {}
        }
    },

    startPolling() {
        this.stopPolling();
        this.pollTimer = setInterval(() => {
            if (!this.active || !this.player) return;
            try {
                const cur = this.player.getCurrentTime ? this.player.getCurrentTime() : 0;
                const dur = this.player.getDuration ? this.player.getDuration() : (Player.currentTrack?.duration || 0);
                if (dur > 0) {
                    Player.onYTTimeUpdate(cur, dur);
                }
            } catch (e) {}
        }, 250);
    },

    stopPolling() {
        if (this.pollTimer) {
            clearInterval(this.pollTimer);
            this.pollTimer = null;
        }
    },

    handleState(state) {
        // 1: PLAYING, 2: PAUSED, 0: ENDED, 3: BUFFERING
        if (state === 1) {
            Player.isPlaying = true;
            Player.onPlayState(true);
        } else if (state === 2) {
            Player.isPlaying = false;
            Player.onPlayState(false);
        } else if (state === 0) {
            this.stopPolling();
            Player.onEnded();
        }
    }
};

const Player = {
    audio: null,
    currentTrack: null,
    queue: [],
    queueIndex: -1,
    isPlaying: false,
    repeatMode: 'off', // off, all, one
    shuffleEnabled: false,
    volume: 80,
    elements: {},
    playedSessionIds: new Set(),
    isAutoFetchingRadio: false,
    activeEngine: 'audio', // 'audio' or 'yt'
    audioCtx: null,
    wakeLock: null,
    _bgAudioInitialized: false,
    _ytBridgeInitialized: false,
    _isMobile: false,

    init() {
        // Detect mobile early for performance decisions
        this._isMobile = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini|Mobile|mobile/i.test(navigator.userAgent) ||
                         (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1) ||
                         window.matchMedia('(pointer: coarse)').matches;

        let existingAudio = document.getElementById('wave-native-audio');
        if (!existingAudio) {
            this.audio = document.createElement('audio');
            this.audio.id = 'wave-native-audio';
            this.audio.crossOrigin = 'anonymous'; // Required for Web Audio Analyser
            this.audio.setAttribute('playsinline', 'true');
            this.audio.setAttribute('webkit-playsinline', 'true');
            this.audio.setAttribute('x-webkit-airplay', 'allow');
            this.audio.preload = 'auto';
            this.audio.style.cssText = 'position:fixed;bottom:-9999px;left:-9999px;width:1px;height:1px;opacity:0.01;pointer-events:none;';
            document.body.appendChild(this.audio);
        } else {
            this.audio = existingAudio;
            this.audio.crossOrigin = 'anonymous';
            this.audio.setAttribute('playsinline', 'true');
            this.audio.setAttribute('webkit-playsinline', 'true');
            this.audio.setAttribute('x-webkit-airplay', 'allow');
            this.audio.preload = 'auto';
            this.audio.style.cssText = 'position:fixed;bottom:-9999px;left:-9999px;width:1px;height:1px;opacity:0.01;pointer-events:none;';
        }
        this.audio.volume = this.volume / 100;

        // LAZY: Do NOT init YTBridge on page load — only when first YT fallback is needed
        // YTBridge loads the entire YouTube iframe API script which wastes bandwidth + CPU on mobile

        this.cacheElements();
        this.bindEvents();
        this.bindAudioEvents();
        this.setupMediaSession();

        // Unlock audio playback on first user touch / click
        const unlockAudio = () => {
            window.removeEventListener('click', unlockAudio);
            window.removeEventListener('touchstart', unlockAudio);
            window.removeEventListener('keydown', unlockAudio);
        };
        window.addEventListener('click', unlockAudio, { passive: true, once: true });
        window.addEventListener('touchstart', unlockAudio, { passive: true, once: true });
        window.addEventListener('keydown', unlockAudio, { passive: true, once: true });

        // Background audio recovery + Wake Lock
        // When user switches back to the app, resume audio if it was playing
        document.addEventListener('visibilitychange', async () => {
            if (document.visibilityState === 'visible') {
                // Resume audio if it was supposed to be playing but iOS paused it
                if (this.isPlaying && this.activeEngine === 'audio' && this.audio.paused && this.audio.src) {
                    try {
                        await this.audio.play();
                    } catch (e) {
                        console.debug('Background audio resume failed:', e);
                    }
                }
                // Re-acquire wake lock
                if (this.isPlaying && 'wakeLock' in navigator) {
                    this.requestWakeLock();
                }
            }
        });

        const savedVolume = localStorage.getItem('wave_volume');
        if (savedVolume !== null) {
            this.volume = parseInt(savedVolume);
            this.audio.volume = this.volume / 100;
            if (this.elements.volumeSlider) {
                this.elements.volumeSlider.value = this.volume;
            }
        }

        if (typeof lucide !== 'undefined') {
            lucide.createIcons();
        }
    },

    // Lazy-init YTBridge only when actually needed (saves CPU + memory on mobile)
    ensureYTBridge() {
        if (!this._ytBridgeInitialized) {
            this._ytBridgeInitialized = true;
            YTBridge.init();
        }
    },

    async requestWakeLock() {
        if ('wakeLock' in navigator && this.isPlaying) {
            try {
                if (this.wakeLock) return;
                this.wakeLock = await navigator.wakeLock.request('screen');
                this.wakeLock.addEventListener('release', () => {
                    this.wakeLock = null;
                });
            } catch (err) {
                console.debug('WakeLock request:', err);
            }
        }
    },

    releaseWakeLock() {
        if (this.wakeLock) {
            this.wakeLock.release().catch(() => {});
            this.wakeLock = null;
        }
    },

    cacheElements() {
        this.elements = {
            playBtn: document.getElementById('btn-play'),
            prevBtn: document.getElementById('btn-prev'),
            nextBtn: document.getElementById('btn-next'),
            shuffleBtn: document.getElementById('btn-shuffle'),
            repeatBtn: document.getElementById('btn-repeat'),
            likeBtn: document.getElementById('btn-like'),
            lyricsBtn: document.getElementById('btn-lyrics'),
            volumeBtn: document.getElementById('btn-volume'),
            volumeSlider: document.getElementById('volume-slider'),
            progressContainer: document.getElementById('progress-container'),
            progressFill: document.getElementById('progress-fill'),
            progressThumb: document.getElementById('progress-thumb'),
            timeCurrent: document.getElementById('time-current'),
            timeDuration: document.getElementById('time-duration'),
            trackName: document.getElementById('player-track-name'),
            artist: document.getElementById('player-artist'),
            artImg: document.getElementById('player-art-img'),
            artContainer: document.getElementById('player-art'),
            trackInfo: document.getElementById('player-track-info'),
            barsIndicator: document.getElementById('player-bars-indicator'),
            downloadBtn: document.getElementById('btn-download'),

            // Mobile-Exclusive Lyrics Controls
            lyricsPlayBtn: document.getElementById('btn-lyrics-play'),
            lyricsPrevBtn: document.getElementById('btn-lyrics-prev'),
            lyricsNextBtn: document.getElementById('btn-lyrics-next'),
            lyricsRepeatBtn: document.getElementById('btn-lyrics-repeat'),
            lyricsLikeBtn: document.getElementById('btn-lyrics-like'),
            lyricsMoreBtn: document.getElementById('btn-lyrics-more'),
            lyricsMoreSheet: document.getElementById('lyrics-more-sheet'),
            lyricsMoreBackdrop: document.getElementById('lyrics-more-backdrop'),
            lyricsMoreClose: document.getElementById('btn-lyrics-more-close'),
            lyricsProgressContainer: document.getElementById('lyrics-progress-container'),
            lyricsProgressFill: document.getElementById('lyrics-progress-fill'),
            lyricsTimeCurrent: document.getElementById('lyrics-time-current'),
            lyricsTimeDuration: document.getElementById('lyrics-time-duration'),
            lyricsArtImg: document.getElementById('lyrics-art-img'),
            lyricsArtFrame: document.getElementById('lyrics-art-frame'),
        };
    },

    bindEvents() {
        this.elements.playBtn?.addEventListener('click', (e) => {
            e.stopPropagation();
            this.togglePlay();
        });
        this.elements.prevBtn?.addEventListener('click', (e) => {
            e.stopPropagation();
            this.previous();
        });
        this.elements.nextBtn?.addEventListener('click', (e) => {
            e.stopPropagation();
            this.next();
        });
        this.elements.shuffleBtn?.addEventListener('click', (e) => {
            e.stopPropagation();
            this.toggleShuffle();
        });
        this.elements.repeatBtn?.addEventListener('click', (e) => {
            e.stopPropagation();
            this.toggleRepeat();
        });
        this.elements.likeBtn?.addEventListener('click', (e) => {
            e.stopPropagation();
            this.toggleLike();
        });
        this.elements.downloadBtn?.addEventListener('click', (e) => {
            e.stopPropagation();
            if (this.currentTrack) {
                downloadSong(
                    this.currentTrack.video_id,
                    this.currentTrack.track_name || this.currentTrack.title,
                    this.currentTrack.artist
                );
            }
        });

        // Mobile Lyrics Controls Event Bindings
        this.elements.lyricsPlayBtn?.addEventListener('click', (e) => {
            e.stopPropagation();
            this.togglePlay();
        });
        this.elements.lyricsPrevBtn?.addEventListener('click', (e) => {
            e.stopPropagation();
            this.previous();
        });
        this.elements.lyricsNextBtn?.addEventListener('click', (e) => {
            e.stopPropagation();
            this.next();
        });
        this.elements.lyricsRepeatBtn?.addEventListener('click', (e) => {
            e.stopPropagation();
            this.toggleRepeat();
        });
        this.elements.lyricsLikeBtn?.addEventListener('click', (e) => {
            e.stopPropagation();
            this.toggleLike();
        });
        this.elements.lyricsMoreBtn?.addEventListener('click', (e) => {
            e.stopPropagation();
            this.toggleLyricsMoreSheet(true);
        });
        this.elements.lyricsMoreBackdrop?.addEventListener('click', () => {
            this.toggleLyricsMoreSheet(false);
        });
        this.elements.lyricsMoreClose?.addEventListener('click', () => {
            this.toggleLyricsMoreSheet(false);
        });
        this.elements.lyricsProgressContainer?.addEventListener('click', (e) => {
            const rect = this.elements.lyricsProgressContainer.getBoundingClientRect();
            const percent = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
            this.seekTo(percent);
        });

        // More Sheet Items Actions
        document.getElementById('lyrics-sheet-download')?.addEventListener('click', () => {
            if (this.currentTrack) {
                downloadSong(
                    this.currentTrack.video_id,
                    this.currentTrack.track_name || this.currentTrack.title,
                    this.currentTrack.artist
                );
            }
            this.toggleLyricsMoreSheet(false);
        });
        document.getElementById('lyrics-sheet-queue')?.addEventListener('click', () => {
            this.toggleLyricsMoreSheet(false);
            document.getElementById('lyrics-overlay')?.classList.add('hidden');
            navigateTo('queue');
        });
        document.getElementById('lyrics-sheet-add-playlist')?.addEventListener('click', () => {
            if (this.currentTrack && typeof Library !== 'undefined') {
                this.toggleLyricsMoreSheet(false);
                Library.openAddToPlaylistModal(this.currentTrack.video_id, this.currentTrack);
            }
        });
        document.getElementById('lyrics-sheet-add-queue')?.addEventListener('click', () => {
            if (this.currentTrack) {
                this.addToQueue(this.currentTrack);
                showToast(`Added "${this.currentTrack.track_name || this.currentTrack.title}" to queue`);
                this.toggleLyricsMoreSheet(false);
            }
        });
        document.getElementById('lyrics-sheet-shuffle')?.addEventListener('click', () => {
            this.toggleShuffle();
            this.updateMoreSheetToggles();
        });
        document.getElementById('lyrics-sheet-repeat')?.addEventListener('click', () => {
            this.toggleRepeat();
            this.updateMoreSheetToggles();
        });
        document.getElementById('lyrics-sheet-artist')?.addEventListener('click', () => {
            if (this.currentTrack?.artist && typeof openArtistPage === 'function') {
                this.toggleLyricsMoreSheet(false);
                document.getElementById('lyrics-overlay')?.classList.add('hidden');
                openArtistPage(this.currentTrack.artist);
            }
        });

        // Clicking on the currently playing track info opens the lyrics & now-playing view
        this.elements.trackInfo?.addEventListener('click', (e) => {
            if (e.target.closest('#player-artist')) {
                e.stopPropagation();
                if (this.currentTrack?.artist && typeof openArtistPage === 'function') {
                    openArtistPage(this.currentTrack.artist);
                }
                return;
            }
            if (!e.target.closest('#btn-like') && !e.target.closest('#btn-download')) {
                this.toggleLyrics();
            }
        });

        // Lyrics button
        this.elements.lyricsBtn?.addEventListener('click', (e) => {
            e.stopPropagation();
            this.toggleLyrics();
        });

        document.getElementById('btn-lyrics-close')?.addEventListener('click', () => {
            document.getElementById('lyrics-overlay')?.classList.add('hidden');
            this.toggleLyricsMoreSheet(false);
        });

        // Volume
        this.elements.volumeSlider?.addEventListener('input', (e) => {
            this.setVolume(parseInt(e.target.value));
        });
        this.elements.volumeBtn?.addEventListener('click', () => this.toggleMute());

        // Progress bar seeking
        this.elements.progressContainer?.addEventListener('click', (e) => {
            const rect = this.elements.progressContainer.getBoundingClientRect();
            const percent = (e.clientX - rect.left) / rect.width;
            this.seekTo(percent);
        });

        // Clear queue
        document.getElementById('btn-clear-queue')?.addEventListener('click', () => {
            this.clearQueue();
        });

        // Queue button in player
        document.getElementById('btn-queue')?.addEventListener('click', () => {
            navigateTo('queue');
        });
    },

    toggleLyricsMoreSheet(show) {
        const sheet = document.getElementById('lyrics-more-sheet');
        if (!sheet) return;
        if (show) {
            sheet.classList.remove('hidden');
            this.updateMoreSheetToggles();
            if (typeof lucide !== 'undefined') {
                lucide.createIcons({ nodes: [sheet] });
            }
        } else {
            sheet.classList.add('hidden');
        }
    },

    updateMoreSheetToggles() {
        const shuffleText = document.getElementById('lyrics-sheet-shuffle-text');
        const repeatText = document.getElementById('lyrics-sheet-repeat-text');
        const queueText = document.getElementById('lyrics-sheet-queue-text');
        if (shuffleText) {
            shuffleText.textContent = `Shuffle: ${this.shuffleEnabled ? 'On' : 'Off'}`;
        }
        if (repeatText) {
            const repeatLabels = { off: 'Off', all: 'All', one: 'One' };
            repeatText.textContent = `Repeat: ${repeatLabels[this.repeatMode] || 'Off'}`;
        }
        if (queueText) {
            const count = this.queue.length;
            queueText.textContent = count > 0 ? `View Queue (${count} song${count > 1 ? 's' : ''})` : 'View Queue / Up Next';
        }
    },

    toggleLyrics() {
        const overlay = document.getElementById('lyrics-overlay');
        if (!overlay) return;

        overlay.classList.toggle('hidden');
        if (!overlay.classList.contains('hidden')) {
            if (this.currentTrack) {
                if (typeof Lyrics !== 'undefined') {
                    Lyrics.loadLyrics(this.currentTrack);
                }
                this.updateTrackUI(this.currentTrack);
            }
            if (this.isPlaying) {
                this.startPrecisionSyncLoop();
            }
            if (typeof lucide !== 'undefined') {
                lucide.createIcons();
            }
        }
    },

    bindAudioEvents() {
        this.audio.addEventListener('timeupdate', () => this.onTimeUpdate());
        this.audio.addEventListener('loadedmetadata', () => this.onLoaded());
        this.audio.addEventListener('ended', () => this.onEnded());
        this.audio.addEventListener('play', () => this.onPlayState(true));
        this.audio.addEventListener('pause', () => this.onPlayState(false));
        this.audio.addEventListener('error', (e) => this.onError(e));
    },

    // ============================================
    // Playback
    // ============================================

    _syncRafId: null,

    /**
     * Precision sync loop for lyrics. On mobile, this ONLY runs when the lyrics
     * overlay is visible (to avoid burning battery with a 60fps rAF loop).
     * On desktop, it runs always for smoother progress bar updates.
     * On mobile without lyrics open, the native 'timeupdate' event handles progress.
     */
    startPrecisionSyncLoop() {
        this.stopPrecisionSyncLoop();

        // On mobile: only run rAF loop if lyrics overlay is actually open
        const lyricsOverlay = document.getElementById('lyrics-overlay');
        const lyricsOpen = lyricsOverlay && !lyricsOverlay.classList.contains('hidden');
        if (this._isMobile && !lyricsOpen) {
            // Mobile without lyrics → rely on timeupdate event (fires ~4x/sec, saves massive battery)
            return;
        }

        const syncLoop = () => {
            if (!this.isPlaying) return;

            // If lyrics closed on mobile, stop the loop
            if (this._isMobile) {
                const lo = document.getElementById('lyrics-overlay');
                if (!lo || lo.classList.contains('hidden')) {
                    this._syncRafId = null;
                    return;
                }
            }

            const curTime = (this.activeEngine === 'yt' && YTBridge.player?.getCurrentTime)
                ? YTBridge.player.getCurrentTime()
                : (this.audio?.currentTime || 0);

            const dur = (this.activeEngine === 'yt' && YTBridge.player?.getDuration)
                ? YTBridge.player.getDuration()
                : (this.audio?.duration || this.currentTrack?.duration || 0);

            if (dur > 0) {
                const percent = (curTime / dur) * 100;
                if (this.elements.progressFill) {
                    this.elements.progressFill.style.width = `${percent}%`;
                }
                if (this.elements.lyricsProgressFill) {
                    this.elements.lyricsProgressFill.style.width = `${percent}%`;
                }
                const curFormatted = formatDuration(curTime);
                if (this.elements.timeCurrent && this.elements.timeCurrent.textContent !== curFormatted) {
                    this.elements.timeCurrent.textContent = curFormatted;
                }
                if (this.elements.lyricsTimeCurrent && this.elements.lyricsTimeCurrent.textContent !== curFormatted) {
                    this.elements.lyricsTimeCurrent.textContent = curFormatted;
                }
            }

            // Real-time sub-millisecond lyrics sync
            if (typeof Lyrics !== 'undefined' && !document.getElementById('lyrics-overlay')?.classList.contains('hidden')) {
                Lyrics.syncToTime(curTime);
            }

            this._syncRafId = requestAnimationFrame(syncLoop);
        };
        this._syncRafId = requestAnimationFrame(syncLoop);
    },

    stopPrecisionSyncLoop() {
        if (this._syncRafId) {
            cancelAnimationFrame(this._syncRafId);
            this._syncRafId = null;
        }
    },

    async play(track) {
        if (!track || !track.video_id) return;

        const prevTrackId = this.currentTrack?.video_id;
        this.currentTrack = track;
        this.updateTrackUI(track);
        this.updateMediaSession(track);

        // Reset previous playing engine
        if (this.activeEngine === 'yt') {
            YTBridge.stop();
        }
        this.activeEngine = 'audio';
        this.ensureYTBridge(); // Lazy-init YTBridge now in case this play fails and we need fallback

        // Save track to local storage recently played
        if (!track.isLocal) {
            this.saveToLocalHistory(track);
        }

        // Prevent double execution on rapid touches or synchronous duplicate events
        const now = Date.now();
        if (this._currentLoadingId === track.video_id && (this.isPlaying || (now - (this._lastPlayAttemptTime || 0) < 600))) {
            return;
        }
        this._currentLoadingId = track.video_id;
        this._lastPlayAttemptTime = now;

        // Set audio stream URL (local blob, extracted link proxy, or standard stream proxy)
        let streamSrc = '';
        const apiBase = (typeof API !== 'undefined' && API.baseUrl) ? API.baseUrl : '';
        if (track.isLocal && track.objectUrl) {
            streamSrc = track.objectUrl;
        } else if (track.is_extracted || (track.video_id && track.video_id.startsWith('ext_'))) {
            streamSrc = `${apiBase}/api/extract/stream/${track.video_id}`;
        } else {
            streamSrc = `${apiBase}/api/stream/${track.video_id}`;
        }

        // Directly set src WITHOUT calling .load() to prevent AbortError in WebKit
        this.audio.src = streamSrc;

        const onPlaybackStarted = () => {
            this.isPlaying = true;
            this.onPlayState(true);
            this.startPrecisionSyncLoop();
            this.postPlayTracking(track, prevTrackId);
            this.checkAndPrefetchRadio(track);
            this._currentLoadingId = null;
        };

        try {
            const playPromise = this.audio.play();
            if (playPromise !== undefined) {
                await playPromise;
            }
            onPlaybackStarted();
        } catch (error) {
            if (error.name === 'AbortError' || error.name === 'NotAllowedError') {
                // In iOS WebKit, play can be queued while buffer initializes: retry on canplay
                const retryPlay = () => {
                    this.audio.removeEventListener('canplay', retryPlay);
                    this.audio.removeEventListener('loadeddata', retryPlay);
                    this.audio.play().then(onPlaybackStarted).catch(() => {});
                };
                this.audio.addEventListener('canplay', retryPlay, { once: true });
                this.audio.addEventListener('loadeddata', retryPlay, { once: true });
                return;
            }
            console.warn('Native audio stream error on cloud, seamlessly switching to client YouTube Audio Engine:', error);
            if (!track.isLocal && track.video_id && !track.video_id.startsWith('ext_')) {
                this.playViaYTBridge(track, prevTrackId);
            } else {
                showToast('Unable to stream audio for this track', 'error');
            }
        }
    },

    playViaYTBridge(track, prevTrackId) {
        this.ensureYTBridge(); // Make sure YTBridge is initialized before using it
        this.activeEngine = 'yt';
        try {
            this.audio.pause();
            this.audio.removeAttribute('src');
            this.audio.load();
        } catch (e) {}

        this.isPlaying = true;
        this.onPlayState(true);
        YTBridge.play(track.video_id);
        this.postPlayTracking(track, prevTrackId);
    },

    postPlayTracking(track, prevTrackId) {
        // Record transition in graph (for online songs)
        if (!track.isLocal && prevTrackId && prevTrackId !== track.video_id) {
            API.post(`/api/recommendations/transition?from_id=${prevTrackId}&to_id=${track.video_id}`).catch(() => {});
        }

        // Record history in MongoDB (for online songs)
        if (!track.isLocal) {
            const meta = typeof getTrackMetadata === 'function' ? getTrackMetadata(track) : null;
            API.post('/api/history', {
                video_id: track.video_id,
                title: (meta?.title) || track.track_name || track.title || 'Unknown',
                artist: (meta?.artist) || track.artist || 'Unknown',
                thumbnail: track.thumbnail || track.album_art || '',
                movie: (meta?.movie) || track.movie || '',
                language: (meta?.language) || track.language || '',
                subtitle: (meta?.subtitle) || track.subtitle || '',
            }).catch(() => {});
        }

        // Update Media Session
        this.updateMediaSession(track);

        // Refresh recently played on Home
        if (typeof loadHomeRecentlyPlayed === 'function') {
            loadHomeRecentlyPlayed(true);
        }

        // Auto-refresh lyrics if overlay is open
        if (!document.getElementById('lyrics-overlay')?.classList.contains('hidden')) {
            if (typeof Lyrics !== 'undefined') {
                Lyrics.loadLyrics(track);
            }
        }

        // Record session tracking
        this.playedSessionIds.add(track.video_id);

        // Fetch language versions in background (non-blocking)
        if (!track.isLocal) {
            this.fetchLanguageVersions(track);
        }

        // Proactively pre-fetch similar radio tracks to ensure infinite continuous playback
        if (!track.isLocal) {
            this.checkAndPrefetchRadio(track);
        }
    },

    // ============================================
    // Language Switcher (Beside Like Button)
    // ============================================

    async fetchLanguageVersions(track) {
        const playerBar = document.getElementById('player-lang-switcher');
        if (!playerBar) return;

        const meta = typeof getTrackMetadata === 'function' ? getTrackMetadata(track) : null;
        const currentLang = track.language || meta?.language || 'Telugu';

        try {
            const trackName = encodeURIComponent(track.track_name || track.title || meta?.title || '');
            const movie = encodeURIComponent(track.movie || meta?.movie || '');
            const data = await API.get(
                `/api/songs/${track.video_id}/languages?track_name=${trackName}&movie=${movie}`
            );

            // Abort updating UI if user has already changed track in the meantime
            if (this.currentTrack?.video_id !== track.video_id) return;

            // Construct complete list of versions including current playing track
            const versionsMap = new Map();

            // 1. Add current track first
            versionsMap.set(currentLang.toLowerCase(), {
                language: currentLang,
                video_id: track.video_id,
                title: track.track_name || track.title || meta?.title || '',
                artist: track.artist || meta?.artist || '',
                thumbnail: track.thumbnail || track.album_art || '',
                duration: track.duration || 0,
                movie: track.movie || meta?.movie || '',
                subtitle: track.subtitle || meta?.subtitle || '',
            });

            // 2. Add alternative versions returned by API
            if (data && Array.isArray(data.versions)) {
                for (const v of data.versions) {
                    if (v && v.language && v.video_id) {
                        const langKey = v.language.toLowerCase();
                        if (!versionsMap.has(langKey)) {
                            versionsMap.set(langKey, {
                                language: v.language,
                                video_id: v.video_id,
                                title: v.title || track.track_name || track.title || '',
                                artist: v.artist || track.artist || '',
                                thumbnail: v.thumbnail || track.thumbnail || track.album_art || '',
                                duration: v.duration || track.duration || 0,
                                movie: v.movie || track.movie || '',
                                subtitle: v.subtitle || '',
                            });
                        }
                    }
                }
            }

            const allVersions = Array.from(versionsMap.values());
            this.currentLanguageVersions = allVersions;
            this.renderLangSwitcher(allVersions, currentLang, track);

        } catch (e) {
            console.debug('Language versions fetch failed:', e);
            playerBar.classList.add('hidden');
        }
    },

    renderLangSwitcher(versions, currentLanguage, currentTrack) {
        const playerBar = document.getElementById('player-lang-switcher');
        const lyricsBar = document.getElementById('lyrics-lang-switcher');
        const sheetBar = document.getElementById('lyrics-sheet-lang-switcher');
        const sheetSection = document.getElementById('lyrics-sheet-lang-section');

        // Only show if at least 2 language options exist
        if (!versions || versions.length < 2) {
            if (playerBar) {
                playerBar.classList.add('hidden');
                playerBar.innerHTML = '';
            }
            if (lyricsBar) {
                lyricsBar.classList.add('hidden');
                lyricsBar.innerHTML = '';
            }
            if (sheetSection) {
                sheetSection.classList.add('hidden');
            }
            if (sheetBar) {
                sheetBar.innerHTML = '';
            }
            return;
        }

        const html = versions.map(v => {
            const isActive = v.language.toLowerCase() === (currentLanguage || '').toLowerCase();
            const trackObj = {
                video_id: v.video_id,
                track_name: v.title || currentTrack?.track_name || currentTrack?.title || 'Unknown',
                title: v.title || currentTrack?.track_name || currentTrack?.title || 'Unknown',
                artist: v.artist || currentTrack?.artist || 'Unknown',
                thumbnail: v.thumbnail || currentTrack?.thumbnail || currentTrack?.album_art || '',
                album_art: v.thumbnail || currentTrack?.thumbnail || currentTrack?.album_art || '',
                duration: v.duration || currentTrack?.duration || 0,
                movie: v.movie || currentTrack?.movie || '',
                language: v.language,
                subtitle: v.subtitle || (v.movie ? `${v.movie} • ${v.language}` : `${v.artist} • ${v.language}`),
            };
            const encoded = encodeURIComponent(JSON.stringify(trackObj));
            return `<button class="lang-pill${isActive ? ' active' : ''}"
                            onclick="event.stopPropagation(); Player.switchToLanguage('${v.language}', '${encoded}')"
                            title="Play in ${v.language}">${v.language}</button>`;
        }).join('');

        if (playerBar) {
            playerBar.innerHTML = html;
            playerBar.classList.remove('hidden');
        }
        if (lyricsBar) {
            lyricsBar.innerHTML = html;
            lyricsBar.classList.remove('hidden');
        }
        if (sheetBar) {
            sheetBar.innerHTML = html;
        }
        if (sheetSection) {
            sheetSection.classList.remove('hidden');
        }
    },

    async switchToLanguage(language, encodedTrack) {
        try {
            const track = JSON.parse(decodeURIComponent(encodedTrack));
            if (!track || !track.video_id) return;

            // If already playing this track ID, don't restart
            if (this.currentTrack?.video_id === track.video_id) {
                return;
            }

            // Immediately mark active pill across all switchers
            document.querySelectorAll('.lang-pill').forEach(btn => {
                if (btn.textContent.trim().toLowerCase() === language.toLowerCase()) {
                    btn.classList.add('active');
                } else {
                    btn.classList.remove('active');
                }
            });

            await this.play(track);
            showToast(`Playing ${language} version`, 'info');

            // Re-render switcher to update active state & payloads
            if (this.currentLanguageVersions) {
                this.renderLangSwitcher(this.currentLanguageVersions, language, track);
            }

            // Refresh lyrics for the new track version
            if (typeof Lyrics !== 'undefined' && !document.getElementById('lyrics-overlay')?.classList.contains('hidden')) {
                Lyrics.loadLyrics(track);
            }
        } catch (e) {
            console.debug('switchToLanguage error:', e);
        }
    },


    togglePlay() {
        if (this.activeEngine === 'yt') {
            if (this.isPlaying) {
                YTBridge.pause();
                this.isPlaying = false;
                this.onPlayState(false);
            } else {
                YTBridge.resume();
                this.isPlaying = true;
                this.onPlayState(true);
            }
            return;
        }

        if (!this.audio.src) {
            if (this.queue.length > 0) {
                this.play(this.queue[0]);
            }
            return;
        }

        if (this.isPlaying) {
            this.audio.pause();
        } else {
            this.audio.play().catch(() => {
                if (this.currentTrack) this.playViaYTBridge(this.currentTrack);
            });
        }
    },

    async next() {
        if (this.queue.length === 0 && !this.currentTrack) return;

        if (this.shuffleEnabled && this.queue.length > 1) {
            let randomIndex;
            do {
                randomIndex = Math.floor(Math.random() * this.queue.length);
            } while (randomIndex === this.queueIndex && this.queue.length > 1);
            this.queueIndex = randomIndex;
            this.play(this.queue[this.queueIndex]);
            this.checkAndPrefetchRadio(this.queue[this.queueIndex]);
            return;
        }

        // Advance in current queue if tracks exist
        if (this.queueIndex + 1 < this.queue.length) {
            this.queueIndex++;
            this.play(this.queue[this.queueIndex]);
            this.checkAndPrefetchRadio(this.queue[this.queueIndex]);
            return;
        }

        if (this.repeatMode === 'all' && this.queue.length > 0) {
            this.queueIndex = 0;
            this.play(this.queue[0]);
            return;
        }

        // Infinite Auto-Play: Fetch more similar radio tracks immediately if queue is at the end
        if (this.currentTrack && !this.currentTrack.isLocal) {
            try {
                showToast('Finding next similar song...', 'info');
                await this.checkAndPrefetchRadio(this.currentTrack, true);
                if (this.queueIndex + 1 < this.queue.length) {
                    this.queueIndex++;
                    this.play(this.queue[this.queueIndex]);
                    return;
                }
            } catch (e) {
                console.debug('Autoplay fallback error:', e);
            }
        }
    },

    previous() {
        if (this.activeEngine === 'yt') {
            const cur = YTBridge.player?.getCurrentTime ? YTBridge.player.getCurrentTime() : 0;
            if (cur > 3) {
                YTBridge.seekTo(0);
                return;
            }
        } else if (this.audio.currentTime > 3) {
            this.audio.currentTime = 0;
            return;
        }

        if (this.queueIndex > 0) {
            this.queueIndex--;
            this.play(this.queue[this.queueIndex]);
        }
    },

    seekTo(percent) {
        if (this.activeEngine === 'yt') {
            const dur = YTBridge.player?.getDuration ? YTBridge.player.getDuration() : (this.currentTrack?.duration || 0);
            if (dur > 0) {
                YTBridge.seekTo(percent * dur);
            }
            return;
        }
        if (this.audio.duration) {
            this.audio.currentTime = percent * this.audio.duration;
        }
    },

    seekToSeconds(seconds) {
        if (this.activeEngine === 'yt') {
            YTBridge.seekTo(seconds);
            return;
        }
        if (this.audio) {
            this.audio.currentTime = seconds;
        }
    },

    seekRelative(seconds) {
        if (this.activeEngine === 'yt') {
            const cur = YTBridge.player?.getCurrentTime ? YTBridge.player.getCurrentTime() : 0;
            const dur = YTBridge.player?.getDuration ? YTBridge.player.getDuration() : (this.currentTrack?.duration || 0);
            YTBridge.seekTo(Math.max(0, Math.min(dur, cur + seconds)));
            return;
        }
        if (this.audio.duration) {
            this.audio.currentTime = Math.max(
                0,
                Math.min(this.audio.duration, this.audio.currentTime + seconds)
            );
        }
    },

    // ============================================
    // Infinite Auto-Play Radio Pre-Fetcher
    // ============================================

    async checkAndPrefetchRadio(currentTrack, force = false) {
        if (!currentTrack) currentTrack = this.currentTrack;
        if (!currentTrack || currentTrack.isLocal || !currentTrack.video_id) return;

        const remaining = this.queue.length - (this.queueIndex + 1);
        if (!force && remaining >= 4) return;
        if (this.isAutoFetchingRadio) return;

        this.isAutoFetchingRadio = true;

        try {
            const meta = typeof getTrackMetadata === 'function' ? getTrackMetadata(currentTrack) : null;
            const title = encodeURIComponent(meta?.title || currentTrack.track_name || currentTrack.title || '');
            const artist = encodeURIComponent(meta?.artist || currentTrack.artist || '');
            const movie = encodeURIComponent(meta?.movie || currentTrack.movie || '');
            const lang = encodeURIComponent(meta?.language || currentTrack.language || 'Telugu');

            const data = await API.get(
                `/api/recommendations/radio?video_id=${currentTrack.video_id}&title=${title}&artist=${artist}&movie=${movie}&language=${lang}&limit=12`
            );

            if (data && Array.isArray(data.tracks) && data.tracks.length > 0) {
                const existingIds = new Set(this.queue.map(t => t.video_id));
                if (this.playedSessionIds) {
                    this.playedSessionIds.forEach(id => existingIds.add(id));
                }

                const newTracks = data.tracks
                    .filter(t => {
                        if (!t || !t.video_id) return false;
                        if (existingIds.has(t.video_id)) return false;
                        // Single-song duration guardrail: reject > 360s (6 min) compilations and playlists
                        const dur = parseInt(t.duration) || 0;
                        if (dur > 360) return false;
                        if (t.track_type === 'playlist') return false;
                        const title = (t.title || t.track_name || '').toLowerCase();
                        if (['jukebox', 'all songs', 'full album', 'full movie', 'movie scenes', 'compilation', 'non stop', 'nonstop'].some(k => title.includes(k))) {
                            return false;
                        }
                        return true;
                    })
                    .map(t => ({
                        ...t,
                        isAutoPlaySuggested: true,
                        vibe_reason: t.vibe_reason || 'Similar Vibe',
                    }));

                if (newTracks.length > 0) {
                    this.queue.push(...newTracks);
                    this.renderQueue();
                    console.info(`✨ Auto-queued ${newTracks.length} similar tracks for continuous play.`);
                }
            }
        } catch (e) {
            console.debug('Radio prefetch failed:', e);
        } finally {
            this.isAutoFetchingRadio = false;
        }
    },

    // ============================================
    // Persistent History
    // ============================================

    saveToLocalHistory(track) {
        try {
            const raw = localStorage.getItem('wave_recently_played');
            let list = raw ? JSON.parse(raw) : [];

            list = list.filter(t => t.video_id !== track.video_id);

            // Snapshot fully-resolved display metadata NOW, while AppState.lastSearchQuery is correct
            const meta = typeof getTrackMetadata === 'function' ? getTrackMetadata(track) : null;

            list.unshift({
                video_id: track.video_id,
                title: (meta?.title) || track.track_name || track.title || 'Unknown',
                track_name: (meta?.title) || track.track_name || track.title || 'Unknown',
                artist: (meta?.artist) || track.artist || 'Unknown',
                thumbnail: track.thumbnail || track.album_art || '',
                album_art: track.thumbnail || track.album_art || '',
                duration: track.duration || 0,
                // Snapshot resolved display metadata - these are frozen so re-render never re-parses
                movie: (meta?.movie) || track.movie || '',
                language: (meta?.language) || track.language || '',
                subtitle: (meta?.subtitle) || track.subtitle || '',
                played_at: new Date().toISOString(),
            });

            list = list.slice(0, 30);
            localStorage.setItem('wave_recently_played', JSON.stringify(list));
        } catch (e) {
            console.debug('Failed to save local history:', e);
        }
    },

    // ============================================
    // Queue
    // ============================================

    setQueue(tracks, startIndex = 0) {
        this.queue = [...tracks];
        this.queueIndex = startIndex;
        this.renderQueue();
        if (tracks[startIndex]) {
            this.checkAndPrefetchRadio(tracks[startIndex]);
        }
    },

    addToQueue(track) {
        // Insert right after user-queued items, before auto-play items
        let insertIndex = this.queue.length;
        for (let i = this.queueIndex + 1; i < this.queue.length; i++) {
            if (this.queue[i].isAutoPlaySuggested) {
                insertIndex = i;
                break;
            }
        }
        track.isAutoPlaySuggested = false;
        this.queue.splice(insertIndex, 0, track);
        this.renderQueue();
    },

    clearQueue() {
        const current = this.queue[this.queueIndex];
        this.queue = current ? [current] : [];
        this.queueIndex = 0;
        this.renderQueue();
        showToast('Queue refreshed with smart recommendations', 'info');
        if (current) {
            this.checkAndPrefetchRadio(current, true);
        }
    },

    renderQueue() {
        const container = document.getElementById('queue-list');
        if (!container) return;

        if (this.queue.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <i data-lucide="list-music"></i>
                    <p>Your queue is empty. Click any song to start playing.</p>
                </div>
            `;
            safeCreateIcons({ nodes: [container] });
            return;
        }

        const nowPlayingTrack = this.queue[this.queueIndex];
        const upNextUser = [];
        const autoPlayTracks = [];

        for (let i = this.queueIndex + 1; i < this.queue.length; i++) {
            const t = this.queue[i];
            if (t.isAutoPlaySuggested) {
                autoPlayTracks.push({ track: t, index: i });
            } else {
                upNextUser.push({ track: t, index: i });
            }
        }

        const renderTrackRow = (track, i, isNowPlaying = false) => {
            const meta = typeof getTrackMetadata === 'function' ? getTrackMetadata(track) : {
                title: track.track_name || track.title || 'Unknown',
                movie: track.movie || '',
                language: track.language || '',
                artist: track.artist || 'Unknown Artist',
                subtitle: track.subtitle || track.artist || 'Unknown Artist'
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

            return `
            <div class="track-row ${isNowPlaying ? 'playing' : ''}"
                 onclick="Player.play(Player.queue[${i}]); Player.queueIndex = ${i};">
                <div class="track-row-art">
                    <img src="${track.thumbnail || track.album_art || ''}"
                         alt="" loading="lazy"
                         onerror="this.style.display='none'">
                </div>
                <div class="track-row-info">
                    <div class="track-row-title">${name}</div>
                    <div class="track-row-artist">${subtitleHtml}</div>
                </div>
                <div class="track-row-duration">${formatDuration(track.duration)}</div>
            </div>
            `;
        };

        let html = '';

        // 1. Now Playing Section
        if (nowPlayingTrack) {
            html += `
                <div class="queue-section-header">
                    <span class="queue-section-title">Now Playing</span>
                </div>
                ${renderTrackRow(nowPlayingTrack, this.queueIndex, true)}
            `;
        }

        // 2. Up Next (User Added) Section
        if (upNextUser.length > 0) {
            html += `
                <div class="queue-section-header">
                    <span class="queue-section-title">Next in Queue</span>
                    <span class="badge">${upNextUser.length} track${upNextUser.length > 1 ? 's' : ''}</span>
                </div>
                ${upNextUser.map(item => renderTrackRow(item.track, item.index, false)).join('')}
            `;
        }

        // 3. Similar Vibes Section (Clean, simple, no badges or icons)
        if (autoPlayTracks.length > 0) {
            html += `
                <div class="queue-section-header">
                    <span class="queue-section-title">Similar Vibes</span>
                </div>
                ${autoPlayTracks.map(item => renderTrackRow(item.track, item.index, false)).join('')}
            `;
        }

        container.innerHTML = html;
        safeCreateIcons({ nodes: [container] });
    },

    // ============================================
    // Volume
    // ============================================

    setVolume(value) {
        this.volume = Math.max(0, Math.min(100, value));
        this.audio.volume = this.volume / 100;
        YTBridge.setVolume(this.volume);
        localStorage.setItem('wave_volume', this.volume);
        this.updateVolumeIcon();
    },

    adjustVolume(delta) {
        this.setVolume(this.volume + delta);
        if (this.elements.volumeSlider) {
            this.elements.volumeSlider.value = this.volume;
        }
    },

    toggleMute() {
        if (this.audio.volume > 0 || (YTBridge.player?.getVolume && YTBridge.player.getVolume() > 0)) {
            this._prevVol = this.volume;
            this.setVolume(0);
        } else {
            this.setVolume(this._prevVol || 80);
        }
        if (this.elements.volumeSlider) {
            this.elements.volumeSlider.value = this.volume;
        }
    },

    updateVolumeIcon() {
        const btn = this.elements.volumeBtn;
        if (!btn) return;

        let iconName = 'volume-2';
        if (this.volume === 0) iconName = 'volume-x';
        else if (this.volume < 50) iconName = 'volume-1';

        btn.innerHTML = `<i data-lucide="${iconName}"></i>`;
        safeCreateIcons({ nodes: [btn] });
    },

    // ============================================
    // Shuffle & Repeat
    // ============================================

    toggleShuffle() {
        this.shuffleEnabled = !this.shuffleEnabled;
        this.elements.shuffleBtn?.classList.toggle('active', this.shuffleEnabled);
        showToast(this.shuffleEnabled ? 'Shuffle on' : 'Shuffle off', 'info');
    },

    toggleRepeat() {
        const modes = ['off', 'all', 'one'];
        const idx = modes.indexOf(this.repeatMode);
        this.repeatMode = modes[(idx + 1) % modes.length];

        this.updateRepeatUI();

        const labels = { off: 'Repeat off', all: 'Repeat all', one: 'Repeat one' };
        showToast(labels[this.repeatMode], 'info');
    },

    updateRepeatUI() {
        const isOff = this.repeatMode === 'off';
        const isOne = this.repeatMode === 'one';

        const btn = this.elements.repeatBtn;
        if (btn) {
            btn.classList.toggle('active', !isOff);
            btn.classList.toggle('repeat-one', isOne);
        }

        const lyricsBtn = this.elements.lyricsRepeatBtn;
        if (lyricsBtn) {
            lyricsBtn.classList.toggle('active', !isOff);
            lyricsBtn.classList.toggle('repeat-one', isOne);
        }

        this.updateMoreSheetToggles();
    },

    // ============================================
    // Likes
    // ============================================

    async toggleLike() {
        if (!this.currentTrack) return;
        if (typeof Library !== 'undefined') {
            await Library.toggleLike(this.currentTrack.video_id, this.currentTrack);
        }
    },

    checkLikeStatus(videoId) {
        if (!videoId) return;
        const isLiked = typeof Library !== 'undefined' ? Library.isLiked(videoId) : false;
        if (typeof Library !== 'undefined') {
            Library.updateLikeUI(videoId, isLiked);
        }
        if (this.elements.lyricsLikeBtn) {
            this.elements.lyricsLikeBtn.classList.toggle('active', isLiked);
            this.elements.lyricsLikeBtn.innerHTML = `<i data-lucide="heart" ${isLiked ? 'style="fill: currentColor;"' : ''}></i>`;
            safeCreateIcons({ nodes: [this.elements.lyricsLikeBtn] });
        }
    },

    // ============================================
    // Audio Events & State Toggles
    // ============================================

    onTimeUpdate() {
        if (this.activeEngine === 'yt') return;
        if (!this.audio.duration) return;

        const percent = (this.audio.currentTime / this.audio.duration) * 100;
        if (this.elements.progressFill) {
            this.elements.progressFill.style.width = `${percent}%`;
        }
        if (this.elements.lyricsProgressFill) {
            this.elements.lyricsProgressFill.style.width = `${percent}%`;
        }

        if (this.elements.timeCurrent) {
            this.elements.timeCurrent.textContent = formatDuration(this.audio.currentTime);
        }
        if (this.elements.lyricsTimeCurrent) {
            this.elements.lyricsTimeCurrent.textContent = formatDuration(this.audio.currentTime);
        }

        if (typeof Lyrics !== 'undefined') {
            Lyrics.syncToTime(this.audio.currentTime);
        }

        // Pre-fetch next radio tracks when song is halfway through to ensure continuous lock-screen play
        if (this.audio.duration > 0 && (this.audio.currentTime / this.audio.duration) > 0.45) {
            this.checkAndPrefetchRadio(this.currentTrack);
        }

        // Keep lock screen scrubber in sync with real-time playback
        if ('mediaSession' in navigator && 'setPositionState' in navigator.mediaSession && !isNaN(this.audio.duration)) {
            try {
                navigator.mediaSession.setPositionState({
                    duration: this.audio.duration,
                    playbackRate: this.audio.playbackRate || 1.0,
                    position: Math.min(this.audio.currentTime, this.audio.duration),
                });
            } catch (e) {}
        }
    },

    onYTTimeUpdate(currentTime, duration) {
        if (!duration || duration <= 0) return;

        const percent = (currentTime / duration) * 100;
        if (this.elements.progressFill) {
            this.elements.progressFill.style.width = `${percent}%`;
        }
        if (this.elements.lyricsProgressFill) {
            this.elements.lyricsProgressFill.style.width = `${percent}%`;
        }

        if (this.elements.timeCurrent) {
            this.elements.timeCurrent.textContent = formatDuration(currentTime);
        }
        if (this.elements.lyricsTimeCurrent) {
            this.elements.lyricsTimeCurrent.textContent = formatDuration(currentTime);
        }

        if (this.elements.timeDuration) {
            this.elements.timeDuration.textContent = formatDuration(duration);
        }
        if (this.elements.lyricsTimeDuration) {
            this.elements.lyricsTimeDuration.textContent = formatDuration(duration);
        }

        if (typeof Lyrics !== 'undefined') {
            Lyrics.syncToTime(currentTime);
        }
    },

    onLoaded() {
        if (this.elements.timeDuration) {
            this.elements.timeDuration.textContent = formatDuration(this.audio.duration);
        }
        if (this.elements.lyricsTimeDuration) {
            this.elements.lyricsTimeDuration.textContent = formatDuration(this.audio.duration);
        }
        this.updatePositionState();
    },

    onEnded() {
        if (this.repeatMode === 'one') {
            if (this.activeEngine === 'yt') {
                YTBridge.seekTo(0);
                YTBridge.resume();
            } else {
                this.audio.currentTime = 0;
                this.audio.play();
            }
        } else {
            this.next();
        }
    },

    onPlayState(playing) {
        this.isPlaying = playing;

        if (playing) {
            this.requestWakeLock();
            this.startPrecisionSyncLoop();
        } else {
            this.releaseWakeLock();
            this.stopPrecisionSyncLoop();
        }

        // Update OS Media Session Playback State (enables lock screen media controls)
        if ('mediaSession' in navigator) {
            navigator.mediaSession.playbackState = playing ? 'playing' : 'paused';
        }

        // Clean, reliable Play/Pause button icon change
        const btn = this.elements.playBtn;
        if (btn) {
            btn.innerHTML = `<i data-lucide="${playing ? 'pause' : 'play'}"></i>`;
            safeCreateIcons({ nodes: [btn] });
        }

        const lyricsPlayBtn = this.elements.lyricsPlayBtn;
        if (lyricsPlayBtn) {
            lyricsPlayBtn.innerHTML = `<i data-lucide="${playing ? 'pause' : 'play'}"></i>`;
            safeCreateIcons({ nodes: [lyricsPlayBtn] });
        }

        // Show/hide animated waveform equalizer bars
        if (this.elements.barsIndicator) {
            this.elements.barsIndicator.classList.toggle('hidden', !playing);
        }

        // Highlight active track rows
        document.querySelectorAll('.track-row').forEach(row => {
            row.classList.toggle('playing', row.dataset.videoId === this.currentTrack?.video_id);
        });
    },

    onError(e) {
        console.warn('Native audio stream error on host:', e);
        if (typeof API !== 'undefined' && API.nodes && API.nodes.length > 1 && API.rotateServer()) {
            console.info('Retrying stream on backup server node...');
            if (this.currentTrack) {
                const curPos = this.audio ? this.audio.currentTime : 0;
                this.loadTrack(this.currentTrack).then(() => {
                    if (curPos > 0 && this.audio) this.audio.currentTime = curPos;
                }).catch(() => {});
                return;
            }
        }
        if (this.currentTrack && !this.currentTrack.isLocal && this.currentTrack.video_id && !this.currentTrack.video_id.startsWith('ext_') && this.activeEngine !== 'yt') {
            console.info('Switching to YouTube Audio Engine for seamless playback...');
            this.playViaYTBridge(this.currentTrack);
        } else {
            this.isPlaying = false;
            this.onPlayState(false);
            if (typeof showToast === 'function') {
                showToast('Unable to stream this track', 'error');
            }
        }
    },

    // ============================================
    // UI Updates
    // ============================================

    updateTrackUI(track) {
        const meta = typeof getTrackMetadata === 'function' ? getTrackMetadata(track) : {
            title: track.track_name || track.title || 'Unknown',
            movie: track.movie || '',
            language: track.language || '',
            artist: track.artist || 'Unknown Artist',
            subtitle: track.subtitle || track.artist || 'Unknown Artist'
        };

        const name = meta.title;
        const sub = meta.movie ? (meta.language ? `${meta.movie} • ${meta.language}` : meta.movie) : (meta.language ? `${meta.artist} • ${meta.language}` : meta.artist);
        const art = track.thumbnail || track.album_art || '';

        if (this.elements.trackName) this.elements.trackName.textContent = name;
        if (this.elements.artist) {
            const isClickable = meta.movie && meta.movie !== 'Wave Music' && meta.movie !== 'Unknown Artist';
            this.elements.artist.innerHTML = isClickable ? `
                <span class="track-movie" onclick="event.stopPropagation(); if (typeof searchForCategory==='function') searchForCategory('${escapeHtml(meta.movie)}')">${escapeHtml(meta.movie)}</span>
                ${meta.language ? `<span class="track-lang-dot">•</span><span class="track-lang-text">${escapeHtml(meta.language)}</span>` : ''}
            ` : (meta.movie ? `
                <span class="track-artist-plain">${escapeHtml(meta.movie)}</span>
                ${meta.language ? `<span class="track-lang-dot">•</span><span class="track-lang-text">${escapeHtml(meta.language)}</span>` : ''}
            ` : `<span class="track-artist-plain">${escapeHtml(sub)}</span>`);
        }

        if (this.elements.artImg && art) {
            this.elements.artImg.src = art;
            this.elements.artContainer?.classList.add('has-art');
        } else {
            this.elements.artContainer?.classList.remove('has-art');
        }

        if (this.elements.lyricsArtImg) {
            if (art) {
                this.elements.lyricsArtImg.src = art;
                this.elements.lyricsArtFrame?.classList.add('has-art');
            } else {
                this.elements.lyricsArtImg.src = '';
                this.elements.lyricsArtFrame?.classList.remove('has-art');
            }
        }

        if (this.elements.progressFill) this.elements.progressFill.style.width = '0%';
        if (this.elements.lyricsProgressFill) this.elements.lyricsProgressFill.style.width = '0%';
        if (this.elements.timeCurrent) this.elements.timeCurrent.textContent = '0:00';
        if (this.elements.lyricsTimeCurrent) this.elements.lyricsTimeCurrent.textContent = '0:00';
        if (track.duration) {
            const formatted = formatDuration(track.duration);
            if (this.elements.timeDuration) this.elements.timeDuration.textContent = formatted;
            if (this.elements.lyricsTimeDuration) this.elements.lyricsTimeDuration.textContent = formatted;
        }

        document.title = `▶ ${name} — ${sub} | Wave`;

        document.querySelectorAll('.track-row').forEach(row => {
            row.classList.toggle('playing', row.dataset.videoId === track.video_id);
        });

        // Update like state for currently playing song
        this.checkLikeStatus(track.video_id);

        // Update OS Media Session (Lock screen metadata and controls)
        this.updateMediaSession(track);
    },

    // ============================================
    // Media Session API (Background / Lock Screen)
    // ============================================

    setupMediaSession() {
        if (!('mediaSession' in navigator)) return;

        // IMPORTANT: Use DIRECT play/pause calls, not togglePlay().
        // The OS sends 'play' when it wants playback to start and 'pause' when it wants it to stop.
        // Using togglePlay() can invert the state if the OS and our state get out of sync.
        try {
            navigator.mediaSession.setActionHandler('play', () => {
                if (this.activeEngine === 'yt') {
                    YTBridge.resume();
                    this.isPlaying = true;
                    this.onPlayState(true);
                } else {
                    this.audio.play().catch(() => {});
                }
            });
        } catch (e) { console.debug('MediaSession play not supported:', e); }

        try {
            navigator.mediaSession.setActionHandler('pause', () => {
                if (this.activeEngine === 'yt') {
                    YTBridge.pause();
                    this.isPlaying = false;
                    this.onPlayState(false);
                } else {
                    this.audio.pause();
                }
            });
        } catch (e) { console.debug('MediaSession pause not supported:', e); }

        // Previous and Next track — these show the |<< and >>| buttons on lock screen
        try {
            navigator.mediaSession.setActionHandler('previoustrack', () => {
                this.previous();
            });
        } catch (e) { console.debug('MediaSession previoustrack not supported:', e); }

        try {
            navigator.mediaSession.setActionHandler('nexttrack', () => {
                this.next();
            });
        } catch (e) { console.debug('MediaSession nexttrack not supported:', e); }

        try {
            navigator.mediaSession.setActionHandler('seekto', (details) => {
                if (details.seekTime !== undefined) {
                    if (this.activeEngine === 'yt') {
                        YTBridge.seekTo(details.seekTime);
                    } else if (this.audio && !isNaN(this.audio.duration)) {
                        this.audio.currentTime = details.seekTime;
                    }
                    this.updatePositionState();
                }
            });
        } catch (e) { console.debug('MediaSession seekto not supported:', e); }
        try { navigator.mediaSession.setActionHandler('seekbackward', null); } catch (e) {}
        try { navigator.mediaSession.setActionHandler('seekforward', null); } catch (e) {}

        try {
            navigator.mediaSession.setActionHandler('stop', () => {
                if (this.activeEngine === 'yt') {
                    YTBridge.pause();
                } else {
                    this.audio.pause();
                }
                this.onPlayState(false);
            });
        } catch (e) { console.debug('MediaSession stop not supported:', e); }
    },

    updateMediaSession(track) {
        if (!track || !('mediaSession' in navigator)) return;

        // Re-affirm Next & Previous track action handlers for this active song
        this.setupMediaSession();

        const meta = typeof getTrackMetadata === 'function' ? getTrackMetadata(track) : null;
        const title = (meta?.title) || track.track_name || track.title || 'Unknown Track';
        const artist = (meta?.movie) || (meta?.artist) || track.artist || 'Wave Music';
        const album = (meta?.movie) || track.movie || 'Wave';
        const rawArt = track.thumbnail || track.album_art || '/static/icons/icon-512.png';
        const origin = window.location.origin;
        const artUrl = rawArt.startsWith('http') ? rawArt : `${origin}${rawArt.startsWith('/') ? '' : '/'}${rawArt}`;

        try {
            navigator.mediaSession.metadata = new MediaMetadata({
                title: title,
                artist: artist,
                album: album,
                artwork: [
                    { src: artUrl, sizes: '96x96', type: 'image/jpeg' },
                    { src: artUrl, sizes: '128x128', type: 'image/jpeg' },
                    { src: artUrl, sizes: '192x192', type: 'image/png' },
                    { src: artUrl, sizes: '256x256', type: 'image/jpeg' },
                    { src: artUrl, sizes: '384x384', type: 'image/jpeg' },
                    { src: artUrl, sizes: '512x512', type: 'image/png' },
                ],
            });
            navigator.mediaSession.playbackState = this.isPlaying ? 'playing' : 'paused';
            this.updatePositionState();
        } catch (e) {
            console.debug('MediaSession metadata error:', e);
        }
    },

    updatePositionState() {
        if ('mediaSession' in navigator && 'setPositionState' in navigator.mediaSession) {
            const dur = (this.activeEngine === 'yt' && YTBridge.player?.getDuration)
                ? YTBridge.player.getDuration()
                : (this.audio?.duration || this.currentTrack?.duration || 0);

            const pos = (this.activeEngine === 'yt' && YTBridge.player?.getCurrentTime)
                ? YTBridge.player.getCurrentTime()
                : (this.audio?.currentTime || 0);

            if (dur > 0 && !isNaN(dur) && !isNaN(pos)) {
                try {
                    navigator.mediaSession.setPositionState({
                        duration: dur,
                        playbackRate: this.audio?.playbackRate || 1.0,
                        position: Math.min(Math.max(0, pos), dur),
                    });
                } catch (e) {}
            }
        }
    },
};

window.Player = Player;
window.YTBridge = YTBridge;

document.addEventListener('DOMContentLoaded', () => {
    Player.init();
});
