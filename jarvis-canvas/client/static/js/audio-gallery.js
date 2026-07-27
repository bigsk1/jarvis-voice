/**
 * Jarvis Canvas - Audio Gallery JavaScript
 */

let audioItems = [];
let filteredAudio = [];
let refreshInProgress = false;
let toastTimer = null;

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
                <div class="audio-art" aria-hidden="true">
                    <div class="audio-wave">${bars}</div>
                    <span class="audio-provider">${escapeHtml(provider)}</span>
                    ${model ? `<span class="audio-model" title="${escapeHtml(model)}">${escapeHtml(model)}</span>` : ''}
                    <span class="audio-format">${escapeHtml(format)}</span>
                    ${duration ? `<span class="audio-duration">${duration}</span>` : ''}
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
    const players = [...document.querySelectorAll('.audio-player')];
    players.forEach(player => {
        player.addEventListener('play', () => {
            players.forEach(other => {
                if (other !== player && !other.paused) other.pause();
            });
        });
    });
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
