/**
 * Wave — Audio Visualizer
 * Canvas-based frequency visualization with iOS-safe background audio preservation.
 * On mobile: visualizer is COMPLETELY DISABLED to save battery (canvas is tiny + low opacity).
 * On desktop: uses Web Audio API for real frequency data visualization.
 */

const Visualizer = {
    canvas: null,
    ctx: null,
    audioContext: null,
    analyser: null,
    sourceNode: null,
    dataArray: null,
    isActive: false,
    animationId: null,
    connected: false,
    isMobile: false,

    barCount: 48,
    barGap: 3,
    smoothing: 0.82,

    init() {
        this.canvas = document.getElementById('visualizer-canvas');
        if (!this.canvas) return;

        this.ctx = this.canvas.getContext('2d');

        // Comprehensive mobile + PWA detection
        this.isMobile = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini|Mobile|mobile/i.test(navigator.userAgent) ||
                        (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1) ||
                        window.matchMedia('(pointer: coarse)').matches ||
                        window.navigator.standalone === true ||
                        window.matchMedia('(display-mode: standalone)').matches ||
                        window.matchMedia('(display-mode: minimal-ui)').matches;

        if (this.isMobile) {
            // On mobile: hide canvas entirely and never start any animation loop.
            // This saves massive battery — the canvas is 60px at 25% opacity, invisible to users.
            this.canvas.style.display = 'none';
            this.connected = true; // Mark as connected so it doesn't try to init later
            return;
        }

        this.resizeCanvas();
        window.addEventListener('resize', () => this.resizeCanvas());
    },

    resizeCanvas() {
        if (!this.canvas) return;
        this.canvas.width = this.canvas.offsetWidth * window.devicePixelRatio;
        this.canvas.height = this.canvas.offsetHeight * window.devicePixelRatio;
        this.ctx.scale(window.devicePixelRatio, window.devicePixelRatio);
    },

    connectToPlayer() {
        // Mobile: do nothing (already handled in init)
        if (this.isMobile) return;

        if (this.connected || !Player?.audio) return;

        try {
            this.audioContext = new (window.AudioContext || window.webkitAudioContext)();
            this.analyser = this.audioContext.createAnalyser();
            this.analyser.fftSize = 256;
            this.analyser.smoothingTimeConstant = this.smoothing;

            this.sourceNode = this.audioContext.createMediaElementSource(Player.audio);
            this.sourceNode.connect(this.analyser);
            this.analyser.connect(this.audioContext.destination);

            this.dataArray = new Uint8Array(this.analyser.frequencyBinCount);
            this.connected = true;
            this.start();
        } catch (error) {
            console.debug('Visualizer audio context init failed:', error);
            // Don't start any fallback animation — just disable
            this.connected = true;
        }
    },

    start() {
        if (this.isMobile || this.isActive) return;
        this.isActive = true;
        this.animate();
    },

    stop() {
        this.isActive = false;
        if (this.animationId) {
            cancelAnimationFrame(this.animationId);
            this.animationId = null;
        }
        if (this.ctx && this.canvas) {
            this.ctx.clearRect(0, 0, this.canvas.offsetWidth, this.canvas.offsetHeight);
        }
    },

    animate() {
        if (!this.isActive) return;
        this.animationId = requestAnimationFrame(() => this.animate());
        this.draw();
    },

    draw() {
        if (!this.ctx || !this.canvas || !this.analyser || !this.dataArray) return;

        const width = this.canvas.offsetWidth;
        const height = this.canvas.offsetHeight;
        this.ctx.clearRect(0, 0, width, height);

        if (!Player || !Player.isPlaying) return;

        this.analyser.getByteFrequencyData(this.dataArray);

        const totalBarWidth = (width - (this.barCount - 1) * this.barGap) / this.barCount;
        const barWidth = Math.max(3, totalBarWidth);

        for (let i = 0; i < this.barCount; i++) {
            const dataIndex = Math.floor((i / this.barCount) * this.dataArray.length * 0.65);
            const value = this.dataArray[dataIndex] || 0;
            const barHeight = Math.max(3, (value / 255) * height * 0.85);

            const x = i * (barWidth + this.barGap);
            const y = height - barHeight;

            const gradient = this.ctx.createLinearGradient(x, height, x, y);
            gradient.addColorStop(0, 'rgba(196, 168, 130, 0.2)');
            gradient.addColorStop(0.5, 'rgba(196, 168, 130, 0.6)');
            gradient.addColorStop(1, 'rgba(168, 139, 101, 0.9)');

            this.ctx.fillStyle = gradient;
            this.ctx.beginPath();
            this.ctx.roundRect(x, y, barWidth, barHeight, [3, 3, 0, 0]);
            this.ctx.fill();
        }
    },
};

document.addEventListener('DOMContentLoaded', () => {
    Visualizer.init();

    const p = window.Player || (typeof Player !== 'undefined' ? Player : null);
    if (p?.audio) {
        p.audio.addEventListener('play', () => {
            if (Visualizer.isMobile) return; // No visualizer on mobile
            if (!Visualizer.connected) {
                Visualizer.connectToPlayer();
            } else {
                Visualizer.start();
            }
        });
        p.audio.addEventListener('pause', () => {
            if (Visualizer.isMobile) return;
            Visualizer.stop();
        });
    }
});
