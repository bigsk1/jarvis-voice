/**
 * Jarvis Canvas - Audio Gallery JavaScript
 */

let audioItems = [];
let filteredAudio = [];
let refreshInProgress = false;
let toastTimer = null;

const STATIC_AUDIO_LEVELS = [
    0.34, 0.68, 0.48, 0.82, 0.56, 0.92, 0.44, 0.74,
    0.52, 0.86, 0.40, 0.64, 0.72, 0.46, 0.76, 0.38,
];
const VISUALIZER_FFT_SIZE = 1024;
const VISUALIZER_MAX_FREQUENCY = 12000;
const VISUALIZER_FLOOR_DB = -78;
const VISUALIZER_CEILING_DB = -2;
const VISUALIZER_TILT_DB_PER_BAND = 2;

class AudioGalleryVisualizer {
    constructor() {
        this.audioContext = null;
        this.analyser = null;
        this.frequencyData = null;
        this.frequencyBands = null;
        this.tracks = new Map();
        this.activeTrack = null;
        this.animationFrame = null;
        this.warnedAboutWebAudio = false;
        this.motionQuery = window.matchMedia
            ? window.matchMedia('(prefers-reduced-motion: reduce)')
            : null;
        this.resizeObserver = window.ResizeObserver
            ? new ResizeObserver(entries => {
                entries.forEach(entry => {
                    const track = [...this.tracks.values()]
                        .find(candidate => candidate.surface === entry.target);
                    if (track) {
                        this.resizeCanvas(track);
                        this.drawCurrentState(track);
                    }
                });
            })
            : null;

        const handleMotionChange = () => this.handleMotionPreference();
        if (this.motionQuery?.addEventListener) {
            this.motionQuery.addEventListener('change', handleMotionChange);
        } else if (this.motionQuery?.addListener) {
            this.motionQuery.addListener(handleMotionChange);
        }

        if (!this.resizeObserver) {
            window.addEventListener('resize', () => {
                this.tracks.forEach(track => {
                    this.resizeCanvas(track);
                    this.drawCurrentState(track);
                });
            });
        }
    }

    get reducedMotion() {
        return Boolean(this.motionQuery?.matches);
    }

    attach() {
        const players = [...document.querySelectorAll('.audio-player')];

        players.forEach(player => {
            player.addEventListener('play', () => {
                players.forEach(other => {
                    if (other !== player && !other.paused) other.pause();
                });
            });

            const card = player.closest('.audio-card');
            const art = card?.querySelector('.audio-art');
            const surface = card?.querySelector('.audio-visualizer');
            const canvas = card?.querySelector('.audio-viz');
            const tooltip = card?.querySelector('.audio-seek-time');
            const durationText = card?.querySelector('.audio-duration-text');
            const context = canvas?.getContext('2d');
            if (!card || !art || !surface || !canvas || !context) return;

            const track = {
                player,
                card,
                art,
                surface,
                canvas,
                context,
                tooltip,
                durationText,
                source: null,
                levels: [...STATIC_AUDIO_LEVELS],
                peaks: [...STATIC_AUDIO_LEVELS],
                hoverProgress: null,
                settleFrame: null,
                disposed: false,
                width: 0,
                height: 0,
                pixelRatio: 1,
            };

            art.classList.add('has-visualizer');
            this.tracks.set(player, track);
            this.bindPlayerEvents(track);
            this.bindSeekEvents(track);
            this.updateDuration(track);
            this.resizeCanvas(track);
            this.drawCurrentState(track);
            this.resizeObserver?.observe(surface);
        });
    }

    resetTracks() {
        this.stopAnimation();
        this.activeTrack = null;
        this.tracks.forEach(track => {
            track.disposed = true;
            if (!track.player.paused) track.player.pause();
            if (track.settleFrame) cancelAnimationFrame(track.settleFrame);
            this.resizeObserver?.unobserve(track.surface);
            try {
                track.source?.disconnect();
            } catch (_error) {
                // A source can already be disconnected during a rapid re-render.
            }
        });
        this.tracks.clear();
    }

    bindPlayerEvents(track) {
        const {player} = track;
        const listen = (eventName, handler) => {
            player.addEventListener(eventName, (...args) => {
                if (!track.disposed) handler(...args);
            });
        };

        listen('play', () => {
            this.start(track);
        });
        listen('playing', () => {
            track.card.classList.remove('is-loading');
        });
        listen('waiting', () => {
            if (!player.paused) track.card.classList.add('is-loading');
        });
        listen('stalled', () => {
            if (!player.paused) track.card.classList.add('is-loading');
        });
        listen('canplay', () => {
            track.card.classList.remove('is-loading');
        });
        listen('pause', () => {
            if (!player.ended) this.settle(track, false);
        });
        listen('ended', () => this.settle(track, true));
        listen('error', () => {
            track.card.classList.remove('is-playing', 'is-loading');
            track.card.classList.add('has-audio-error');
            this.settle(track, false);
        });
        listen('loadedmetadata', () => {
            this.updateDuration(track);
            this.updateSlider(track);
            this.drawCurrentState(track);
        });
        listen('durationchange', () => this.updateDuration(track));
        listen('timeupdate', () => {
            this.updateSlider(track);
            if (track !== this.activeTrack || this.reducedMotion || this.animationFrame === null) {
                this.drawCurrentState(track);
            }
        });
        listen('seeked', () => this.drawCurrentState(track));
    }

    bindSeekEvents(track) {
        const {surface} = track;

        surface.addEventListener('pointermove', event => {
            const progress = this.progressFromPointer(track, event);
            if (progress === null) return;
            track.hoverProgress = progress;
            this.positionSeekTooltip(track, progress);
            this.drawCurrentState(track);
        });
        surface.addEventListener('pointerleave', () => {
            track.hoverProgress = null;
            if (track.tooltip) track.tooltip.classList.remove('is-visible');
            this.drawCurrentState(track);
        });
        surface.addEventListener('click', event => {
            const progress = this.progressFromPointer(track, event);
            if (progress !== null) this.seekToProgress(track, progress);
        });
        surface.addEventListener('keydown', event => {
            const duration = track.player.duration;
            if (!Number.isFinite(duration) || duration <= 0) return;

            let nextTime = track.player.currentTime;
            const step = event.shiftKey ? 15 : 5;
            if (event.key === 'ArrowLeft') nextTime -= step;
            else if (event.key === 'ArrowRight') nextTime += step;
            else if (event.key === 'Home') nextTime = 0;
            else if (event.key === 'End') nextTime = duration;
            else return;

            event.preventDefault();
            track.player.currentTime = Math.max(0, Math.min(duration, nextTime));
            this.updateSlider(track);
            this.drawCurrentState(track);
        });
    }

    start(track) {
        this.cancelSettle(track);
        track.card.classList.remove('has-audio-error');
        track.card.classList.add('is-playing');
        this.activeTrack = track;
        this.updateSlider(track);

        if (this.reducedMotion) {
            this.drawCurrentState(track);
            return;
        }

        if (!this.ensureAudioGraph(track)) {
            this.drawCurrentState(track);
            return;
        }

        this.audioContext.resume().catch(error => {
            console.warn('Unable to resume AudioContext:', error);
        });
        this.stopAnimation();
        this.animate();
    }

    ensureAudioGraph(track) {
        try {
            if (!this.audioContext) {
                const AudioContextClass = window.AudioContext || window.webkitAudioContext;
                if (!AudioContextClass) return false;
                this.audioContext = new AudioContextClass();
                this.analyser = this.audioContext.createAnalyser();
                this.analyser.fftSize = VISUALIZER_FFT_SIZE;
                this.analyser.minDecibels = -95;
                this.analyser.maxDecibels = -3;
                this.analyser.smoothingTimeConstant = 0.76;
                this.analyser.connect(this.audioContext.destination);
                this.frequencyData = new Float32Array(this.analyser.frequencyBinCount);
                this.frequencyBands = this.buildFrequencyBands();
            }

            if (!track.source) {
                track.source = this.audioContext.createMediaElementSource(track.player);
                track.source.connect(this.analyser);
            }
            return true;
        } catch (error) {
            if (!this.warnedAboutWebAudio) {
                console.warn('Live audio visualization is unavailable; using the static waveform.', error);
                this.warnedAboutWebAudio = true;
            }
            return false;
        }
    }

    animate() {
        if (!this.activeTrack || this.activeTrack.player.paused || this.reducedMotion) {
            this.stopAnimation();
            return;
        }

        this.analyser.getFloatFrequencyData(this.frequencyData);
        const levels = this.frequencyLevels();
        const track = this.activeTrack;
        track.levels = levels;
        track.peaks = track.peaks.map((peak, index) => (
            Math.max(levels[index], peak - 0.012)
        ));
        this.updateArtworkEnergy(track, levels);
        this.draw(track, levels, true);
        this.animationFrame = requestAnimationFrame(() => this.animate());
    }

    stopAnimation() {
        if (this.animationFrame !== null) cancelAnimationFrame(this.animationFrame);
        this.animationFrame = null;
    }

    settle(track, ended) {
        if (track === this.activeTrack) {
            this.stopAnimation();
            this.activeTrack = null;
        }
        track.card.classList.remove('is-playing', 'is-loading');
        this.cancelSettle(track);
        this.updateArtworkEnergy(track, STATIC_AUDIO_LEVELS, true);

        if (this.reducedMotion) {
            track.levels = [...STATIC_AUDIO_LEVELS];
            track.peaks = [...STATIC_AUDIO_LEVELS];
            this.drawCurrentState(track);
            return;
        }

        const from = [...track.levels];
        const startedAt = performance.now();
        const duration = ended ? 440 : 280;
        const animateSettle = now => {
            const progress = Math.min(1, (now - startedAt) / duration);
            const eased = 1 - Math.pow(1 - progress, 3);
            let levels;

            if (ended && progress < 0.42) {
                const contraction = progress / 0.42;
                levels = from.map(level => level + (0.08 - level) * contraction);
            } else {
                const returnProgress = ended ? (progress - 0.42) / 0.58 : eased;
                const origin = ended ? STATIC_AUDIO_LEVELS.map(() => 0.08) : from;
                levels = origin.map((level, index) => (
                    level + (STATIC_AUDIO_LEVELS[index] - level) * returnProgress
                ));
            }

            track.levels = levels;
            this.draw(track, levels, false);
            if (progress < 1) {
                track.settleFrame = requestAnimationFrame(animateSettle);
            } else {
                track.settleFrame = null;
                track.levels = [...STATIC_AUDIO_LEVELS];
                track.peaks = [...STATIC_AUDIO_LEVELS];
                this.drawCurrentState(track);
            }
        };
        track.settleFrame = requestAnimationFrame(animateSettle);
    }

    cancelSettle(track) {
        if (track.settleFrame) cancelAnimationFrame(track.settleFrame);
        track.settleFrame = null;
    }

    frequencyLevels() {
        const decibelRange = VISUALIZER_CEILING_DB - VISUALIZER_FLOOR_DB;
        return this.frequencyBands.map(([start, end], index) => {
            let total = 0;
            for (let bin = start; bin < end; bin += 1) total += this.frequencyData[bin];
            const averageDb = total / Math.max(1, end - start);

            // Music naturally carries more energy in its low bands. A gentle
            // upward spectral tilt keeps treble readable without crushing bass
            // against the ceiling and hiding its movement.
            const compensatedDb = averageDb + index * VISUALIZER_TILT_DB_PER_BAND;
            const normalized = Math.max(
                0,
                Math.min(1, (compensatedDb - VISUALIZER_FLOOR_DB) / decibelRange)
            );
            return Math.max(0.08, Math.pow(normalized, 0.82));
        });
    }

    buildFrequencyBands() {
        const bandCount = STATIC_AUDIO_LEVELS.length;
        const binWidth = this.audioContext.sampleRate / this.analyser.fftSize;
        const maxBin = Math.min(
            this.frequencyData.length - 1,
            Math.floor(VISUALIZER_MAX_FREQUENCY / binWidth)
        );
        const bands = [];
        let start = 1;

        for (let index = 0; index < bandCount; index += 1) {
            const logarithmicEnd = Math.round(
                Math.exp(Math.log(maxBin) * ((index + 1) / bandCount))
            );
            const end = Math.min(maxBin, Math.max(start + 1, logarithmicEnd));
            bands.push([start, end]);
            start = end;
        }
        return bands;
    }

    resizeCanvas(track) {
        const rect = track.surface.getBoundingClientRect();
        const width = Math.max(1, rect.width);
        const height = Math.max(1, rect.height);
        const pixelRatio = Math.min(window.devicePixelRatio || 1, 2);
        const renderWidth = Math.round(width * pixelRatio);
        const renderHeight = Math.round(height * pixelRatio);

        if (track.canvas.width !== renderWidth || track.canvas.height !== renderHeight) {
            track.canvas.width = renderWidth;
            track.canvas.height = renderHeight;
        }
        track.width = width;
        track.height = height;
        track.pixelRatio = pixelRatio;
    }

    drawCurrentState(track) {
        this.draw(track, track.levels, track === this.activeTrack && !this.reducedMotion);
    }

    draw(track, levels, showPeaks) {
        if (!track.width || !track.height) return;
        const {context, width, height, pixelRatio} = track;
        context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
        context.clearRect(0, 0, width, height);

        const progress = this.playbackProgress(track);
        if (progress > 0) {
            const progressGradient = context.createLinearGradient(0, 0, width, 0);
            progressGradient.addColorStop(0, 'rgba(57, 197, 207, 0.04)');
            progressGradient.addColorStop(1, 'rgba(163, 113, 247, 0.22)');
            context.fillStyle = progressGradient;
            context.fillRect(0, 0, width * progress, height);
            context.fillStyle = 'rgba(215, 183, 255, 0.48)';
            context.fillRect(Math.max(0, width * progress - 1), 0, 1, height);
        }

        const horizontalPadding = Math.min(44, width * 0.13);
        const availableWidth = Math.max(80, width - horizontalPadding * 2);
        const gap = Math.max(3, Math.min(7, availableWidth / 44));
        const barWidth = Math.max(
            3,
            Math.min(10, (availableWidth - gap * (levels.length - 1)) / levels.length)
        );
        const totalWidth = levels.length * barWidth + (levels.length - 1) * gap;
        const startX = (width - totalWidth) / 2;
        const centerY = height / 2 + 4;
        const maximumHeight = height * 0.66;
        const gradient = context.createLinearGradient(0, centerY + maximumHeight / 2, 0, centerY - maximumHeight / 2);
        gradient.addColorStop(0, '#39c5cf');
        gradient.addColorStop(1, '#d7b7ff');

        levels.forEach((level, index) => {
            const barHeight = Math.max(14, maximumHeight * level);
            const x = startX + index * (barWidth + gap);
            const y = centerY - barHeight / 2;
            context.fillStyle = gradient;
            context.shadowColor = 'rgba(57, 197, 207, 0.34)';
            context.shadowBlur = track === this.activeTrack ? 12 : 7;
            this.roundedRect(context, x, y, barWidth, barHeight, barWidth / 2);
            context.fill();

            if (showPeaks) {
                const peakHeight = Math.max(14, maximumHeight * track.peaks[index]);
                const peakY = centerY - peakHeight / 2;
                context.shadowBlur = 0;
                context.fillStyle = 'rgba(255, 255, 255, 0.78)';
                context.fillRect(x + 1, peakY, Math.max(1, barWidth - 2), 1.5);
            }
        });
        context.shadowBlur = 0;

        if (track.hoverProgress !== null) {
            const hoverX = width * track.hoverProgress;
            context.fillStyle = 'rgba(255, 255, 255, 0.78)';
            context.fillRect(Math.max(0, hoverX - 0.75), 12, 1.5, height - 24);
        }
    }

    roundedRect(context, x, y, width, height, radius) {
        const safeRadius = Math.min(radius, width / 2, height / 2);
        context.beginPath();
        context.moveTo(x + safeRadius, y);
        context.lineTo(x + width - safeRadius, y);
        context.quadraticCurveTo(x + width, y, x + width, y + safeRadius);
        context.lineTo(x + width, y + height - safeRadius);
        context.quadraticCurveTo(x + width, y + height, x + width - safeRadius, y + height);
        context.lineTo(x + safeRadius, y + height);
        context.quadraticCurveTo(x, y + height, x, y + height - safeRadius);
        context.lineTo(x, y + safeRadius);
        context.quadraticCurveTo(x, y, x + safeRadius, y);
        context.closePath();
    }

    updateArtworkEnergy(track, levels, clear = false) {
        const bass = clear
            ? 0
            : levels.slice(0, 4).reduce((total, level) => total + level, 0) / 4;
        track.art.style.setProperty('--audio-glow-opacity', String(0.08 + bass * 0.42));
        track.art.style.setProperty('--audio-glow-scale', String(1 + bass * 0.08));
    }

    playbackProgress(track) {
        const duration = track.player.duration;
        if (!Number.isFinite(duration) || duration <= 0) return 0;
        return Math.max(0, Math.min(1, track.player.currentTime / duration));
    }

    progressFromPointer(track, event) {
        const duration = track.player.duration;
        if (!Number.isFinite(duration) || duration <= 0) return null;
        const rect = track.surface.getBoundingClientRect();
        if (!rect.width) return null;
        return Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width));
    }

    seekToProgress(track, progress) {
        const duration = track.player.duration;
        if (!Number.isFinite(duration) || duration <= 0) return;
        track.player.currentTime = progress * duration;
        this.updateSlider(track);
        this.drawCurrentState(track);
    }

    positionSeekTooltip(track, progress) {
        if (!track.tooltip) return;
        const duration = track.player.duration;
        track.tooltip.textContent = formatDuration(progress * duration);
        track.tooltip.style.left = `${Math.max(8, Math.min(92, progress * 100))}%`;
        track.tooltip.classList.add('is-visible');
    }

    updateDuration(track) {
        const duration = track.player.duration;
        if (!Number.isFinite(duration) || duration <= 0) return;
        if (track.durationText) track.durationText.textContent = formatDuration(duration);
        track.surface.tabIndex = 0;
        track.surface.setAttribute('aria-disabled', 'false');
        this.updateSlider(track);
    }

    updateSlider(track) {
        const duration = track.player.duration;
        const currentTime = Number.isFinite(track.player.currentTime)
            ? track.player.currentTime
            : 0;
        const percent = Number.isFinite(duration) && duration > 0
            ? Math.round((currentTime / duration) * 100)
            : 0;
        track.surface.setAttribute('aria-valuenow', String(percent));
        track.surface.setAttribute(
            'aria-valuetext',
            Number.isFinite(duration) && duration > 0
                ? `${formatDuration(currentTime)} of ${formatDuration(duration)}`
                : 'Duration unavailable'
        );
    }

    handleMotionPreference() {
        if (!this.activeTrack) return;
        if (this.reducedMotion) {
            this.stopAnimation();
            this.activeTrack.levels = [...STATIC_AUDIO_LEVELS];
            this.activeTrack.peaks = [...STATIC_AUDIO_LEVELS];
            this.updateArtworkEnergy(this.activeTrack, STATIC_AUDIO_LEVELS, true);
            this.drawCurrentState(this.activeTrack);
        } else if (!this.activeTrack.player.paused && this.ensureAudioGraph(this.activeTrack)) {
            this.audioContext.resume().catch(() => {});
            this.animate();
        }
    }
}

const audioVisualizer = new AudioGalleryVisualizer();

async function fetchAudio() {
    try {
        const response = await fetch('/api/gallery/audio');
        if (!response.ok) throw new Error(`Audio request failed (${response.status})`);
        const data = await response.json();
        audioItems = data.audio || [];
        document.getElementById('audioCount').textContent = `${audioItems.length} ${audioItems.length === 1 ? 'track' : 'tracks'}`;
        document.getElementById('totalSize').textContent = formatSize(data.total_size || 0);
        updateProviderFilter();
        filterAudio();
    } catch (error) {
        console.error('Failed to fetch audio:', error);
        showToast('Failed to load audio', 'error');
    }
}

function updateProviderFilter() {
    const select = document.getElementById('providerFilter');
    const selected = select.value;
    const providers = [...new Set(
        audioItems
            .map(item => item.provider)
            .filter(Boolean)
    )].sort((a, b) => a.localeCompare(b));

    select.innerHTML = '';
    select.add(new Option('All Providers', 'all'));
    providers.forEach(provider => select.add(new Option(provider, provider.toLowerCase())));
    select.value = [...select.options].some(option => option.value === selected) ? selected : 'all';
}

function filterAudio() {
    const search = document.getElementById('searchInput').value.trim().toLowerCase();
    const provider = document.getElementById('providerFilter').value;
    const favoritesOnly = document.getElementById('favoriteFilter').value === 'favorites';

    filteredAudio = audioItems.filter(item => {
        const searchable = [
            item.title,
            item.name,
            item.genre,
            item.mood,
            item.tempo,
            ...(Array.isArray(item.tags) ? item.tags : []),
        ].filter(Boolean).join(' ').toLowerCase();

        if (search && !searchable.includes(search)) return false;
        if (provider !== 'all' && (item.provider || '').toLowerCase() !== provider) return false;
        if (favoritesOnly && !item.favorite) return false;
        return true;
    });

    sortAudio();
}

function sortAudio() {
    const sort = document.getElementById('sortSelect').value;
    filteredAudio.sort((a, b) => {
        const aTitle = getTrackTitle(a);
        const bTitle = getTrackTitle(b);
        switch (sort) {
            case 'date-asc': return new Date(a.modified) - new Date(b.modified);
            case 'name-asc': return aTitle.localeCompare(bTitle);
            case 'name-desc': return bTitle.localeCompare(aTitle);
            case 'size-desc': return b.size - a.size;
            case 'size-asc': return a.size - b.size;
            case 'duration-desc': return (b.duration_seconds || 0) - (a.duration_seconds || 0);
            case 'duration-asc': return (a.duration_seconds || 0) - (b.duration_seconds || 0);
            case 'date-desc':
            default:
                return new Date(b.modified) - new Date(a.modified);
        }
    });
    renderGallery();
}

function renderGallery() {
    const gallery = document.getElementById('audioGallery');
    const emptyState = document.getElementById('emptyState');
    audioVisualizer.resetTracks();

    if (filteredAudio.length === 0) {
        gallery.innerHTML = '';
        emptyState.style.display = 'block';
        return;
    }

    emptyState.style.display = 'none';
    gallery.innerHTML = filteredAudio.map((item, index) => {
        const title = getTrackTitle(item);
        const provider = item.provider || 'Unknown';
        const model = String(item.model || '').trim();
        const format = (item.format || extensionFromName(item.name) || 'audio').toUpperCase();
        const duration = item.duration_seconds ? formatDuration(item.duration_seconds) : '';
        const detailParts = [item.genre, item.mood, item.instrumental ? 'Instrumental' : null].filter(Boolean);
        const detail = detailParts.length ? detailParts.join(' · ') : 'Generated audio';
        const favoriteLabel = item.favorite ? 'Remove favorite' : 'Add favorite';
        const bars = [34, 68, 48, 82, 56, 92, 44, 74, 52, 86, 40, 64]
            .map(height => `<span style="--bar-height:${height}%"></span>`)
            .join('');

        return `
            <article class="audio-card${item.favorite ? ' is-favorite' : ''}" data-index="${index}">
                <div class="audio-art">
                    <div class="audio-wave" aria-hidden="true">${bars}</div>
                    <div
                        class="audio-visualizer"
                        role="slider"
                        tabindex="${duration ? '0' : '-1'}"
                        aria-label="Seek in ${escapeHtml(title)}"
                        aria-valuemin="0"
                        aria-valuemax="100"
                        aria-valuenow="0"
                        aria-valuetext="0:00 of ${duration || 'unknown duration'}"
                        aria-disabled="${duration ? 'false' : 'true'}"
                    >
                        <canvas class="audio-viz" aria-hidden="true"></canvas>
                        <span class="audio-seek-time" aria-hidden="true">0:00</span>
                    </div>
                    <span class="audio-provider">${escapeHtml(provider)}</span>
                    ${model ? `<span class="audio-model" title="${escapeHtml(model)}">${escapeHtml(model)}</span>` : ''}
                    <span class="audio-format">${escapeHtml(format)}</span>
                    <span class="audio-duration" aria-hidden="true">
                        <span class="audio-play-status"></span>
                        <span class="audio-duration-text">${duration || '--:--'}</span>
                    </span>
                    <button
                        type="button"
                        class="audio-favorite"
                        aria-label="${favoriteLabel}"
                        aria-pressed="${item.favorite ? 'true' : 'false'}"
                        title="${favoriteLabel}"
                        onclick="event.stopPropagation(); toggleFavoriteByIndex(${index})"
                    >${item.favorite ? '♥' : '♡'}</button>
                </div>
                <div class="audio-info">
                    <h2 class="audio-title" title="${escapeHtml(title)}">${escapeHtml(title)}</h2>
                    <p class="audio-detail">${escapeHtml(detail)}</p>
                    <audio
                        class="audio-player"
                        controls
                        preload="metadata"
                        src="/api/gallery/audio/${encodeURIComponent(item.name)}"
                    ></audio>
                    <div class="audio-meta">
                        <span>${formatDate(item.modified)}</span>
                        <span>${formatSize(item.size)}</span>
                    </div>
                    <div class="audio-actions">
                        <button class="btn btn-primary" onclick="downloadByIndex(${index})">⬇️ Download</button>
                        <button class="btn btn-danger" onclick="deleteByIndex(${index})" aria-label="Delete ${escapeHtml(title)}" title="Delete">🗑️</button>
                    </div>
                </div>
            </article>
        `;
    }).join('');

    setupExclusivePlayback();
}

function setupExclusivePlayback() {
    audioVisualizer.attach();
}

function getTrackTitle(item) {
    return item.title || formatAudioName(item.name);
}

function formatAudioName(name) {
    return name
        .replace(/^music_/, '')
        .replace(/_\d{8}_\d{6}\.[^.]+$/i, '')
        .replace(/\.[^.]+$/, '')
        .replace(/_/g, ' ')
        .replace(/\b\w/g, letter => letter.toUpperCase());
}

function extensionFromName(name) {
    const match = String(name || '').match(/\.([^.]+)$/);
    return match ? match[1] : '';
}

function formatDate(dateString) {
    const date = new Date(dateString);
    return date.toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric',
        year: date.getFullYear() !== new Date().getFullYear() ? 'numeric' : undefined,
    });
}

function formatSize(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDuration(seconds) {
    const totalSeconds = Math.max(0, Math.round(seconds));
    const minutes = Math.floor(totalSeconds / 60);
    const remainder = totalSeconds % 60;
    return `${minutes}:${remainder.toString().padStart(2, '0')}`;
}

function escapeHtml(value) {
    return String(value || '').replace(/[&<>"']/g, character => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;',
    })[character]);
}

async function toggleFavoriteByIndex(index) {
    const item = filteredAudio[index];
    if (!item) return;
    const favorite = !item.favorite;

    try {
        const response = await fetch(
            `/api/gallery/audio/${encodeURIComponent(item.name)}/favorite`,
            {
                method: 'PATCH',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({favorite}),
            }
        );
        if (!response.ok) throw new Error('Favorite update failed');
        const result = await response.json();
        item.favorite = result.favorite;
        item.favorited_at = result.favorited_at;
        const sourceItem = audioItems.find(candidate => candidate.name === item.name);
        if (sourceItem) {
            sourceItem.favorite = result.favorite;
            sourceItem.favorited_at = result.favorited_at;
        }

        if (document.getElementById('favoriteFilter').value === 'favorites' && !favorite) {
            filterAudio();
        } else {
            renderGallery();
        }
        showToast(favorite ? 'Added to favorites' : 'Removed from favorites');
    } catch (error) {
        console.error('Favorite update failed:', error);
        showToast('Failed to update favorite', 'error');
    }
}

function downloadByIndex(index) {
    const item = filteredAudio[index];
    if (item) downloadAudio(item.name);
}

async function downloadAudio(filename) {
    try {
        showToast('Preparing audio...');
        const response = await fetch(`/api/gallery/audio/${encodeURIComponent(filename)}/download`);
        if (!response.ok) throw new Error('Audio download failed');
        const blob = await response.blob();
        const file = new File([blob], filename, {type: blob.type || 'audio/mpeg'});
        const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent)
            || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);

        if (isIOS && navigator.canShare && navigator.canShare({files: [file]})) {
            await navigator.share({files: [file]});
        } else {
            const blobUrl = URL.createObjectURL(blob);
            const anchor = document.createElement('a');
            anchor.href = blobUrl;
            anchor.download = filename;
            document.body.appendChild(anchor);
            anchor.click();
            setTimeout(() => {
                URL.revokeObjectURL(blobUrl);
                anchor.remove();
            }, 100);
        }
        showToast('Download started');
    } catch (error) {
        if (error.name !== 'AbortError') {
            console.error('Audio download failed:', error);
            showToast('Download failed', 'error');
        }
    }
}

function deleteByIndex(index) {
    const item = filteredAudio[index];
    if (item) deleteAudio(item.name);
}

async function deleteAudio(filename) {
    if (!confirm(`Delete "${filename}"?\n\nThis cannot be undone.`)) return;
    document.querySelectorAll('.audio-player').forEach(player => player.pause());

    try {
        const response = await fetch(`/api/gallery/audio/${encodeURIComponent(filename)}`, {
            method: 'DELETE',
        });
        if (!response.ok) {
            const result = await response.json();
            throw new Error(result.error || 'Audio deletion failed');
        }
        showToast('Audio deleted');
        await fetchAudio();
    } catch (error) {
        console.error('Audio deletion failed:', error);
        showToast(error.message || 'Failed to delete audio', 'error');
    }
}

function setRefreshLoading(isLoading) {
    const button = document.getElementById('refreshBtn');
    button.classList.toggle('is-refreshing', isLoading);
    button.disabled = isLoading;
    button.setAttribute('aria-busy', isLoading ? 'true' : 'false');
    const label = button.querySelector('.refresh-btn-label');
    if (label) label.textContent = isLoading ? 'Refreshing…' : 'Refresh';
}

async function refreshGallery() {
    if (refreshInProgress) return;
    refreshInProgress = true;
    setRefreshLoading(true);
    try {
        await fetchAudio();
    } finally {
        refreshInProgress = false;
        setRefreshLoading(false);
    }
}

function showToast(message, type = 'success') {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.className = `toast active${type === 'error' ? ' error' : ''}`;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
        toast.classList.remove('active');
    }, 2500);
}

document.addEventListener('DOMContentLoaded', fetchAudio);
