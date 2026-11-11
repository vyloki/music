/**
 * Wave — Local Songs Importer & Song Downloader
 * IndexedDB storage for offline/imported music files, drag-and-drop file parser,
 * and 1-click song downloader.
 */

const LocalLibrary = {
    db: null,
    dbName: 'wave_local_db',
    dbVersion: 1,
    tracks: [],

    async init() {
        await this.initDB();
        await this.loadLocalTracks();
    },

    initDB() {
        return new Promise((resolve, reject) => {
            const request = indexedDB.open(this.dbName, this.dbVersion);

            request.onupgradeneeded = (e) => {
                const db = e.target.result;
                if (!db.objectStoreNames.contains('tracks')) {
                    db.createObjectStore('tracks', { keyPath: 'id', autoIncrement: true });
                }
            };

            request.onsuccess = (e) => {
                this.db = e.target.result;
                resolve(this.db);
            };

            request.onerror = (e) => {
                console.error('IndexedDB error:', e);
                reject(e);
            };
        });
    },

    async loadLocalTracks() {
        if (!this.db) return [];

        return new Promise((resolve) => {
            const tx = this.db.transaction('tracks', 'readonly');
            const store = tx.objectStore('tracks');
            const req = store.getAll();

            req.onsuccess = () => {
                this.tracks = req.result || [];
                // Create object URLs for playback
                this.tracks.forEach(track => {
                    if (track.fileBlob && !track.objectUrl) {
                        track.objectUrl = URL.createObjectURL(track.fileBlob);
                    }
                });
                resolve(this.tracks);
            };

            req.onerror = () => {
                resolve([]);
            };
        });
    },

    async importFiles(files) {
        if (!files || files.length === 0) return;

        let importedCount = 0;
        showToast(`Importing ${files.length} audio file(s)...`, 'info');

        for (const file of files) {
            if (!file.type.startsWith('audio/') && !file.name.match(/\.(mp3|wav|m4a|ogg|flac|aac)$/i)) {
                continue;
            }

            try {
                const duration = await this.getAudioDuration(file);
                const cleanName = file.name.replace(/\.[^/.]+$/, "");
                const parts = cleanName.split('-');
                let title = cleanName;
                let artist = "Local Artist";

                if (parts.length > 1) {
                    artist = parts[0].trim();
                    title = parts.slice(1).join('-').trim();
                }

                const trackObj = {
                    title: title,
                    track_name: title,
                    artist: artist,
                    duration: Math.round(duration),
                    fileSize: file.size,
                    fileName: file.name,
                    fileType: file.type || 'audio/mpeg',
                    fileBlob: file,
                    isLocal: true,
                    importedAt: new Date().toISOString(),
                };

                await this.saveTrackToDB(trackObj);
                importedCount++;
            } catch (err) {
                console.error('Error importing file:', file.name, err);
            }
        }

        await this.loadLocalTracks();
        showToast(`Imported ${importedCount} local song(s)!`, 'success');

        if (typeof Library !== 'undefined' && Library.activeTab === 'local') {
            this.renderLocalTab();
        }
    },

    getAudioDuration(file) {
        return new Promise((resolve) => {
            const tempUrl = URL.createObjectURL(file);
            const audio = new Audio();
            audio.preload = 'metadata';
            audio.onloadedmetadata = () => {
                URL.revokeObjectURL(tempUrl);
                resolve(audio.duration || 0);
            };
            audio.onerror = () => {
                URL.revokeObjectURL(tempUrl);
                resolve(0);
            };
            audio.src = tempUrl;
        });
    },

    saveTrackToDB(track) {
        return new Promise((resolve, reject) => {
            if (!this.db) return reject('DB not open');
            const tx = this.db.transaction('tracks', 'readwrite');
            const store = tx.objectStore('tracks');
            const req = store.add(track);

            req.onsuccess = () => resolve(req.result);
            req.onerror = (e) => reject(e);
        });
    },

    async deleteTrack(id) {
        if (!this.db) return;
        return new Promise((resolve) => {
            const tx = this.db.transaction('tracks', 'readwrite');
            const store = tx.objectStore('tracks');
            store.delete(id);
            tx.oncomplete = async () => {
                await this.loadLocalTracks();
                this.renderLocalTab();
                showToast('Local track removed', 'info');
                resolve();
            };
        });
    },

    renderLocalTab() {
        const container = document.getElementById('library-content');
        if (!container) return;

        container.innerHTML = `
            <div class="local-import-zone" id="local-drop-zone">
                <input type="file" id="local-file-input" multiple accept="audio/*,.mp3,.wav,.m4a,.ogg,.flac,.aac" style="display:none;">
                <div class="drop-zone-content">
                    <i data-lucide="upload-cloud"></i>
                    <h3>Import Songs from Your Device</h3>
                    <p>Drag & drop audio files here (.mp3, .wav, .m4a, .flac) or click browse</p>
                    <button class="btn btn-primary" onclick="document.getElementById('local-file-input').click()">
                        <i data-lucide="folder-plus"></i> Browse Audio Files
                    </button>
                </div>
            </div>

            <div class="section-header-row" style="margin-top: 24px;">
                <h2 class="section-title">Imported Songs (${this.tracks.length})</h2>
                ${this.tracks.length > 0 ? `
                    <button class="btn btn-ghost" onclick="LocalLibrary.playAllLocal()">
                        <i data-lucide="play"></i> Play All
                    </button>
                ` : ''}
            </div>

            <div class="local-track-list" id="local-track-list">
                ${this.tracks.length === 0 ? `
                    <div class="empty-state">
                        <i data-lucide="disc"></i>
                        <p>No local songs imported yet. Click browse above to add songs from your device!</p>
                    </div>
                ` : `
                    <div class="track-list">
                        ${this.tracks.map((track, i) => `
                            <div class="track-row" onclick="LocalLibrary.playLocalTrack(${i})">
                                <div class="track-row-art" style="display:flex;align-items:center;justify-content:center;background:var(--bg-secondary);color:var(--accent-dark);">
                                    <i data-lucide="music"></i>
                                </div>
                                <div class="track-row-info">
                                    <div class="track-row-title">${escapeHtml(track.title)}</div>
                                    <div class="track-row-artist">${escapeHtml(track.artist)} • ${(track.fileSize / (1024*1024)).toFixed(1)} MB</div>
                                </div>
                                <div class="track-row-duration">${formatDuration(track.duration)}</div>
                                <div class="track-row-actions">
                                    <button class="btn-icon" onclick="event.stopPropagation(); LocalLibrary.deleteTrack(${track.id})" title="Delete">
                                        <i data-lucide="trash-2"></i>
                                    </button>
                                </div>
                            </div>
                        `).join('')}
                    </div>
                `}
            </div>
        `;

        if (window.safeCreateIcons) {
            window.safeCreateIcons({ nodes: [container] });
        } else if (typeof lucide !== 'undefined' && lucide?.createIcons) {
            lucide.createIcons({ nodes: [container] });
        }

        // Bind file picker
        const fileInput = document.getElementById('local-file-input');
        fileInput?.addEventListener('change', (e) => {
            this.importFiles(e.target.files);
        });

        // Bind drag & drop
        const dropZone = document.getElementById('local-drop-zone');
        if (dropZone) {
            dropZone.addEventListener('dragover', (e) => {
                e.preventDefault();
                dropZone.classList.add('drag-active');
            });
            dropZone.addEventListener('dragleave', () => {
                dropZone.classList.remove('drag-active');
            });
            dropZone.addEventListener('drop', (e) => {
                e.preventDefault();
                dropZone.classList.remove('drag-active');
                if (e.dataTransfer.files) {
                    this.importFiles(e.dataTransfer.files);
                }
            });
        }
    },

    playLocalTrack(index) {
        const track = this.tracks[index];
        if (!track) return;

        if (!track.objectUrl && track.fileBlob) {
            track.objectUrl = URL.createObjectURL(track.fileBlob);
        }

        const playableTrack = {
            video_id: `local_${track.id}`,
            title: track.title,
            track_name: track.title,
            artist: track.artist,
            thumbnail: '',
            duration: track.duration,
            isLocal: true,
            objectUrl: track.objectUrl,
        };

        Player.setQueue(this.tracks.map(t => ({
            video_id: `local_${t.id}`,
            title: t.title,
            track_name: t.title,
            artist: t.artist,
            thumbnail: '',
            duration: t.duration,
            isLocal: true,
            objectUrl: t.objectUrl,
        })), index);

        Player.play(playableTrack);
    },

    playAllLocal() {
        if (this.tracks.length > 0) {
            this.playLocalTrack(0);
        }
    }
};

// ============================================
// 1-Click Song Downloader
// ============================================

function downloadSong(videoId, title, artist) {
    if (!videoId) return;

    if (videoId.startsWith('local_')) {
        showToast('This is already a local file on your device', 'info');
        return;
    }

    const safeTitle = encodeURIComponent(title || 'song');
    const safeArtist = encodeURIComponent(artist || 'artist');
    const downloadUrl = `/api/stream/${videoId}/download?title=${safeTitle}&artist=${safeArtist}`;

    showToast(`Downloading "${title || 'song'}"...`, 'info', 4000);

    const a = document.createElement('a');
    a.href = downloadUrl;
    a.download = `${artist || 'Artist'} - ${title || 'Song'}.mp3`;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => a.remove(), 1000);
}

document.addEventListener('DOMContentLoaded', () => {
    LocalLibrary.init();
});
