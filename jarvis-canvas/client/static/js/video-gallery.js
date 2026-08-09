/**
 * Jarvis Canvas - Video Gallery JavaScript
 */

let videos = [];
let filteredVideos = [];
let currentVideo = null;
let refreshInProgress = false;
let xaiVideoShareStatus = { available: false, allowed_ttl_days: [], max_video_bytes: 0 };
let currentVideoSharePreview = null;
let currentVideoShareFilename = null;

async function fetchVideoShareStatus() {
    try {
        const response = await fetch('/api/xai-video-shares/status');
        const data = await response.json();
        if (response.ok && data.ok) {
            xaiVideoShareStatus = data;
            configureVideoShareTtl();
            if (videos.length) renderGallery();
        }
    } catch (err) {
        console.debug('xAI video sharing is unavailable:', err);
    }
}

function configureVideoShareTtl() {
    const select = document.getElementById('videoShareTtl');
    if (!select) return;
    const allowed = xaiVideoShareStatus.allowed_ttl_days || [1, 7, 30];
    const selected = Number(xaiVideoShareStatus.default_ttl_days || 7);
    select.innerHTML = allowed.map(days => (
        `<option value="${days}" ${Number(days) === selected ? 'selected' : ''}>${days} day${Number(days) === 1 ? '' : 's'}</option>`
    )).join('');
}

function canShareVideo(vid) {
    return Boolean(
        xaiVideoShareStatus.available &&
        vid &&
        String(vid.name || '').toLowerCase().endsWith('.mp4') &&
        Number(vid.size || 0) > 0 &&
        Number(vid.size || 0) <= Number(xaiVideoShareStatus.max_video_bytes || 0)
    );
}

async function fetchVideos() {
    try {
        const response = await fetch('/api/gallery/videos');
        const data = await response.json();
        videos = data.videos || [];
        document.getElementById('videoCount').textContent = `${videos.length} videos`;
        document.getElementById('totalSize').textContent = formatSize(data.total_size || 0);
        filterVideos();
    } catch (err) {
        console.error('Failed to fetch videos:', err);
        showToast('Failed to load videos', 'error');
    }
}

function filterVideos() {
    const search = document.getElementById('searchInput').value.toLowerCase();
    const providerFilter = document.getElementById('providerFilter').value;
    
    filteredVideos = videos.filter(vid => {
        // Text search
        if (search && !vid.name.toLowerCase().includes(search)) {
            return false;
        }
        
        // Provider filter
        if (providerFilter !== 'all') {
            const vidProvider = (vid.provider || detectProvider(vid.name, vid.tags) || '').toLowerCase();
            if (!vidProvider.includes(providerFilter)) {
                return false;
            }
        }
        
        return true;
    });
    sortVideos();
}

function sortVideos() {
    const sort = document.getElementById('sortSelect').value;
    
    filteredVideos.sort((a, b) => {
        switch (sort) {
            case 'date-desc': return new Date(b.modified) - new Date(a.modified);
            case 'date-asc': return new Date(a.modified) - new Date(b.modified);
            case 'name-asc': return a.name.localeCompare(b.name);
            case 'name-desc': return b.name.localeCompare(a.name);
            case 'size-desc': return b.size - a.size;
            case 'size-asc': return a.size - b.size;
            case 'duration-desc': return (b.duration || 0) - (a.duration || 0);
            case 'duration-asc': return (a.duration || 0) - (b.duration || 0);
            default: return 0;
        }
    });
    
    renderGallery();
}

function renderGallery() {
    const gallery = document.getElementById('videoGallery');
    const emptyState = document.getElementById('emptyState');
    
    if (filteredVideos.length === 0) {
        gallery.innerHTML = '';
        emptyState.style.display = 'block';
        return;
    }
    
    emptyState.style.display = 'none';
    
    gallery.innerHTML = filteredVideos.map((vid, index) => {
        // Use provider from API if available, otherwise detect from tags/filename
        const provider = vid.provider || detectProvider(vid.name, vid.tags);
        const model = String(vid.model || '').trim();
        const duration = vid.duration ? formatDuration(vid.duration) : '';
        
        return `
        <div class="video-card" data-index="${index}">
            <div class="video-wrapper" onclick="openLightboxByIndex(${index})">
                <video data-src="/api/gallery/videos/${encodeURIComponent(vid.name)}" 
                       poster="/api/gallery/videos/${encodeURIComponent(vid.name)}/thumbnail"
                       preload="none"
                       muted></video>
                <div class="video-play-overlay">
                    <div class="video-play-icon">▶</div>
                </div>
                ${provider || model ? `
                    <div class="video-badges">
                        ${provider ? `<span class="video-provider">${escapeHtml(provider)}</span>` : ''}
                        ${model ? `<span class="video-model" title="${escapeHtml(model)}">${escapeHtml(model)}</span>` : ''}
                    </div>
                ` : ''}
                ${duration ? `<span class="video-duration">${duration}</span>` : ''}
            </div>
            <div class="video-info">
                <div class="video-name" title="${escapeHtml(vid.name)}">${escapeHtml(formatVideoName(vid.name))}</div>
                <div class="video-meta">
                    <span>${formatDate(vid.modified)}</span>
                    <span>${formatSize(vid.size)}</span>
                </div>
                <div class="video-actions">
                    <div class="video-actions-left">
                        <button class="btn btn-primary" onclick="event.stopPropagation(); downloadByIndex(${index})">⬇️ Download</button>
                        ${canShareVideo(vid) ? `<button class="btn btn-public" onclick="event.stopPropagation(); shareByIndex(${index})">🔗 Share</button>` : ''}
                    </div>
                    <div class="video-actions-right">
                        <button class="btn btn-danger" onclick="event.stopPropagation(); deleteByIndex(${index})">🗑️</button>
                    </div>
                </div>
            </div>
        </div>
    `}).join('');
    
    // Lazy-load videos as they scroll into view + hover preview
    setupLazyLoad();
    setupHoverPreviews();
}

let lazyObserver = null;

function setupLazyLoad() {
    // Disconnect previous observer if gallery re-renders
    if (lazyObserver) lazyObserver.disconnect();
    
    lazyObserver = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (!entry.isIntersecting) return;
            const video = entry.target.querySelector('video');
            if (video && video.dataset.src && !video.src) {
                video.src = video.dataset.src;
                video.preload = 'metadata';
            }
            lazyObserver.unobserve(entry.target);
        });
    }, {
        rootMargin: '200px'  // Start loading 200px before card scrolls into view
    });
    
    document.querySelectorAll('.video-card').forEach(card => {
        lazyObserver.observe(card);
    });
}

function setupHoverPreviews() {
    document.querySelectorAll('.video-card').forEach(card => {
        const video = card.querySelector('video');
        const overlay = card.querySelector('.video-play-overlay');
        
        card.addEventListener('mouseenter', () => {
            // Ensure src is loaded before trying to play (lazy-load may not have fired yet)
            if (!video.src && video.dataset.src) {
                video.src = video.dataset.src;
                video.preload = 'metadata';
            }
            video.play().catch(() => {});
            overlay.style.opacity = '0';
        });
        
        card.addEventListener('mouseleave', () => {
            video.pause();
            video.currentTime = 0;
            overlay.style.opacity = '1';
        });
    });
}

function detectProvider(name, tags = []) {
    // First check tags (most reliable source)
    if (tags && tags.length) {
        if (tags.includes('openai')) return 'OpenAI';
        if (tags.includes('gemini')) return 'Gemini';
        if (tags.includes('xai')) return 'xAI';
        if (tags.includes('runway')) return 'Runway';
    }
    
    // Fallback: detect provider from filename patterns
    const lower = name.toLowerCase();
    
    // Check for explicit provider markers
    if (lower.includes('sora')) return 'OpenAI';
    if (lower.includes('gemini') || lower.includes('veo')) return 'Gemini';
    if (lower.includes('runway')) return 'Runway';
    if (lower.includes('pika')) return 'Pika';
    if (lower.includes('kling')) return 'Kling';
    
    // Default to xAI for video_ prefix (generated by generate_video tool)
    if (lower.startsWith('video_')) return 'xAI';
    
    return null;
}

function formatVideoName(name) {
    // Clean up generated video names for display
    return name
        .replace(/^video_/, '')
        .replace(/_\d{8}_\d{6}\.(mp4|webm|mov)$/i, '')
        .replace(/_/g, ' ')
        .substring(0, 60) + (name.length > 60 ? '...' : '');
}

function formatDate(dateStr) {
    const date = new Date(dateStr);
    return date.toLocaleDateString('en-US', { 
        month: 'short', 
        day: 'numeric',
        year: date.getFullYear() !== new Date().getFullYear() ? 'numeric' : undefined
    });
}

function formatSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

function formatDuration(seconds) {
    if (!seconds) return '';
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    if (mins > 0) {
        return `${mins}:${secs.toString().padStart(2, '0')}`;
    }
    return `${secs}s`;
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function openLightboxByIndex(index) {
    if (index >= 0 && index < filteredVideos.length) {
        const name = filteredVideos[index].name;
        if (name) openLightbox(name);
    }
}

function downloadByIndex(index) {
    if (index >= 0 && index < filteredVideos.length) {
        downloadDirect(filteredVideos[index].name);
    }
}

function shareByIndex(index) {
    if (index >= 0 && index < filteredVideos.length) {
        openVideoShareDialog(filteredVideos[index].name);
    }
}

function deleteByIndex(index) {
    if (index >= 0 && index < filteredVideos.length) {
        deleteVideo(filteredVideos[index].name);
    }
}

function openLightbox(filename) {
    if (!filename || filename === 'null' || filename === 'undefined') return;
    currentVideo = filename;
    const video = document.getElementById('lightboxVideo');
    video.src = `/api/gallery/videos/${encodeURIComponent(filename)}`;
    document.getElementById('lightboxFilename').textContent = filename;
    const selectedVideo = videos.find(vid => vid.name === filename);
    document.getElementById('lightboxShareBtn').hidden = !canShareVideo(selectedVideo);
    document.getElementById('videoLightbox').classList.add('active');
    document.body.style.overflow = 'hidden';
    video.play().catch(() => {});
}

function shareCurrentVideo() {
    if (currentVideo) openVideoShareDialog(currentVideo);
}

function closeLightbox(event) {
    if (event && event.target !== document.getElementById('videoLightbox')) return;
    const video = document.getElementById('lightboxVideo');
    video.pause();
    video.src = '';
    document.getElementById('videoLightbox').classList.remove('active');
    document.body.style.overflow = '';
    currentVideo = null;
}

function downloadVideo() {
    if (currentVideo) downloadDirect(currentVideo);
}

async function downloadDirect(filename) {
    // Use download endpoint with Content-Disposition header
    const url = `/api/gallery/videos/${encodeURIComponent(filename)}/download`;
    const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) || 
                  (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
    
    try {
        showToast('Preparing video...');
        const response = await fetch(url);
        if (!response.ok) throw new Error('Network response was not ok');
        
        const blob = await response.blob();
        // Ensure .mp4 extension for iOS to recognize as video
        const safeName = filename.endsWith('.mp4') ? filename : `${filename}.mp4`;
        const file = new File([blob], safeName, { type: 'video/mp4' });

        if (isIOS && navigator.canShare && navigator.canShare({ files: [file] })) {
            // CRITICAL: Only pass 'files'. Adding title/text breaks "Save Video" option.
            await navigator.share({ files: [file] });
            showToast('Done!');
        } else {
            // Desktop and fallback
            const blobUrl = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = blobUrl;
            a.download = safeName;
            document.body.appendChild(a);
            a.click();
            
            setTimeout(() => {
                URL.revokeObjectURL(blobUrl);
                document.body.removeChild(a);
            }, 100);
            
            showToast('Download started');
        }
    } catch (err) {
        if (err.name !== 'AbortError') {
            console.error('Download failed:', err);
            showToast('Download failed', 'error');
        }
    }
}

function updateVideoSharePublishState() {
    const button = document.getElementById('publishVideoShareBtn');
    const confirmed = document.getElementById('videoShareConfirm')?.checked;
    button.disabled = !(currentVideoSharePreview && confirmed);
}

async function readApiError(response) {
    try {
        const data = await response.json();
        return data.error || data.message || data.detail || `Request failed (${response.status})`;
    } catch (_err) {
        return `Request failed (${response.status})`;
    }
}

async function openVideoShareDialog(filename) {
    const selectedVideo = videos.find(vid => vid.name === filename);
    if (!canShareVideo(selectedVideo)) {
        showToast('This video is not eligible for xAI public sharing', 'error');
        return;
    }

    currentVideoShareFilename = filename;
    currentVideoSharePreview = null;
    document.getElementById('videoShareFilename').textContent = filename;
    document.getElementById('videoSharePreview').textContent = 'Checking the retained MP4…';
    document.getElementById('videoShareConfirm').checked = false;
    document.getElementById('videoShareResult').hidden = true;
    document.getElementById('videoShareHistory').textContent = 'Loading…';
    updateVideoSharePublishState();
    document.getElementById('videoShareModal').classList.add('active');
    document.body.style.overflow = 'hidden';

    await Promise.allSettled([
        loadVideoSharePreview(filename),
        loadVideoShareHistory(filename),
    ]);
}

function closeVideoShareDialog(event) {
    if (event && event.target !== document.getElementById('videoShareModal')) return;
    document.getElementById('videoShareModal').classList.remove('active');
    if (!document.getElementById('videoLightbox').classList.contains('active')) {
        document.body.style.overflow = '';
    }
    currentVideoShareFilename = null;
    currentVideoSharePreview = null;
}

async function loadVideoSharePreview(filename) {
    const response = await fetch('/api/xai-video-shares/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename }),
    });
    if (!response.ok) {
        const message = await readApiError(response);
        document.getElementById('videoSharePreview').textContent = message;
        throw new Error(message);
    }
    const data = await response.json();
    if (currentVideoShareFilename !== filename) return;
    currentVideoSharePreview = data.preview;
    const duration = data.preview.duration ? formatDuration(data.preview.duration) : 'unknown length';
    document.getElementById('videoSharePreview').innerHTML = `
        <strong>Ready to publish</strong>
        <span>${escapeHtml(formatSize(data.preview.video_bytes))} · ${escapeHtml(duration)}</span>
    `;
    updateVideoSharePublishState();
}

async function loadVideoShareHistory(filename) {
    const response = await fetch(`/api/xai-video-shares/list?filename=${encodeURIComponent(filename)}`);
    if (!response.ok) {
        document.getElementById('videoShareHistory').textContent = await readApiError(response);
        return;
    }
    const data = await response.json();
    if (currentVideoShareFilename === filename) renderVideoShareHistory(data.shares || []);
}

function renderVideoShareHistory(shares) {
    const container = document.getElementById('videoShareHistory');
    if (!shares.length) {
        container.innerHTML = '<p class="video-share-empty">No public shares yet.</p>';
        return;
    }
    container.innerHTML = shares.map(share => {
        const status = String(share.status || 'unknown');
        const active = status === 'active' || status === 'revoked_cleanup_pending';
        const url = String(share.public_url || '');
        return `
            <div class="video-share-row">
                <div class="video-share-row-meta">
                    <strong>${escapeHtml(status.replaceAll('_', ' '))}</strong>
                    <span>Expires ${escapeHtml(formatShareDate(share.expires_at))}</span>
                </div>
                <div class="video-share-row-actions">
                    ${url ? `<button class="btn btn-secondary" type="button" onclick="copyVideoShareUrl('${escapeHtml(url)}')">Copy URL</button>` : ''}
                    ${url ? `<a class="btn btn-secondary" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">Open</a>` : ''}
                    ${active ? `<button class="btn btn-danger" type="button" onclick="revokeVideoShare('${escapeHtml(share.share_id)}')">Revoke</button>` : ''}
                </div>
            </div>
        `;
    }).join('');
}

function formatShareDate(value) {
    if (!value) return 'unknown';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return date.toLocaleString();
}

function copyVideoShareUrlLegacy(url) {
    const textarea = document.createElement('textarea');
    const previousFocus = document.activeElement;
    textarea.value = url;
    textarea.setAttribute('readonly', '');
    textarea.style.position = 'fixed';
    textarea.style.left = '-9999px';
    textarea.style.opacity = '0';
    document.body.appendChild(textarea);
    textarea.focus();
    textarea.select();
    textarea.setSelectionRange(0, textarea.value.length);

    let copied = false;
    try {
        copied = document.execCommand('copy');
    } catch (_err) {
        copied = false;
    }
    textarea.remove();
    if (previousFocus && typeof previousFocus.focus === 'function') previousFocus.focus();
    return copied;
}

async function copyVideoShareUrl(url) {
    let copied = false;

    // The modern Clipboard API is normally unavailable on LAN HTTP origins.
    // Avoid awaiting a guaranteed rejection so Firefox retains the click's
    // user activation for the synchronous legacy copy fallback.
    if (window.isSecureContext && navigator.clipboard?.writeText) {
        try {
            await navigator.clipboard.writeText(url);
            copied = true;
        } catch (_err) {
            copied = false;
        }
    }

    if (!copied) copied = copyVideoShareUrlLegacy(url);
    if (copied) {
        showToast('Public URL copied');
        return;
    }

    window.prompt('Automatic copy was blocked. Press Ctrl+C or Cmd+C, then Enter:', url);
}

async function publishVideoShare() {
    if (!currentVideoShareFilename || !currentVideoSharePreview) return;
    const button = document.getElementById('publishVideoShareBtn');
    button.disabled = true;
    button.textContent = 'Publishing…';
    try {
        const response = await fetch('/api/xai-video-shares/publish', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                filename: currentVideoShareFilename,
                ttl_days: Number(document.getElementById('videoShareTtl').value),
                expected_video_sha256: currentVideoSharePreview.video_sha256,
                confirmed: document.getElementById('videoShareConfirm').checked,
            }),
        });
        if (!response.ok) throw new Error(await readApiError(response));
        const data = await response.json();
        const result = document.getElementById('videoShareResult');
        result.hidden = false;
        result.innerHTML = `
            <strong>Video published</strong>
            <a href="${escapeHtml(data.share.public_url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(data.share.public_url)}</a>
            <button class="btn btn-secondary" type="button" onclick="copyVideoShareUrl('${escapeHtml(data.share.public_url)}')">Copy URL</button>
        `;
        document.getElementById('videoShareConfirm').checked = false;
        showToast('Public video URL created');
        await loadVideoShareHistory(currentVideoShareFilename);
    } catch (err) {
        showToast(err.message || 'Video publish failed', 'error');
    } finally {
        button.textContent = 'Publish Video';
        updateVideoSharePublishState();
    }
}

async function revokeVideoShare(shareId) {
    if (!confirm('Revoke this public URL and delete the xAI file now?')) return;
    try {
        const response = await fetch('/api/xai-video-shares/revoke', {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ share_id: shareId }),
        });
        if (!response.ok) throw new Error(await readApiError(response));
        showToast('Public video share revoked');
        await loadVideoShareHistory(currentVideoShareFilename);
    } catch (err) {
        showToast(err.message || 'Failed to revoke public video', 'error');
    }
}

async function deleteVideo(filename) {
    if (!filename || filename === 'null' || filename === 'undefined') {
        showToast('Cannot delete: no video selected', 'error');
        return;
    }
    if (!confirm(`Delete "${filename}"?\n\nThis cannot be undone.`)) return;
    
    await requestVideoDeletion(filename, false);
}

async function requestVideoDeletion(filename, revokePublicShares) {
    try {
        const response = await fetch('/api/video-actions/delete', {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                filename,
                revoke_public_shares: revokePublicShares,
            }),
        });

        if (response.ok) {
            showToast(revokePublicShares ? 'Public copies revoked and video deleted' : 'Video deleted');
            refreshGallery();
            return;
        }

        const data = await response.json();
        if (response.status === 409 && data.code === 'active_public_video_shares') {
            const count = (data.active_shares || []).length;
            const confirmed = confirm(
                `This video has ${count} active public share${count === 1 ? '' : 's'}.\n\n` +
                'Revoke the public copies, delete the xAI files, and then delete the local video?'
            );
            if (confirmed) await requestVideoDeletion(filename, true);
            return;
        }
        showToast(data.error || data.message || 'Failed to delete', 'error');
    } catch (err) {
        showToast('Failed to delete video', 'error');
    }
}

function deleteFromLightbox() {
    const filename = currentVideo || document.getElementById('lightboxFilename')?.textContent?.trim();
    if (filename && filename !== 'null') {
        closeLightbox();
        deleteVideo(filename);
    } else {
        showToast('Cannot delete: no video selected', 'error');
    }
}

function setRefreshLoading(isLoading) {
    const btn = document.getElementById('refreshBtn');
    if (!btn) return;
    btn.classList.toggle('is-refreshing', isLoading);
    btn.disabled = isLoading;
    btn.setAttribute('aria-busy', isLoading ? 'true' : 'false');
    const label = btn.querySelector('.refresh-btn-label');
    if (label) label.textContent = isLoading ? 'Refreshing…' : 'Refresh';
}

async function refreshGallery() {
    if (refreshInProgress) return;
    refreshInProgress = true;
    setRefreshLoading(true);
    try {
        await fetchVideos();
    } finally {
        refreshInProgress = false;
        setRefreshLoading(false);
    }
}

function showToast(message, type = 'success') {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.className = 'toast active' + (type === 'error' ? ' error' : '');
    setTimeout(() => toast.classList.remove('active'), 3000);
}

// Keyboard shortcuts
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        if (document.getElementById('videoShareModal').classList.contains('active')) {
            closeVideoShareDialog();
        } else {
            closeLightbox();
        }
    }
    if (e.key === 'ArrowRight' && currentVideo) navigateVideo(1);
    if (e.key === 'ArrowLeft' && currentVideo) navigateVideo(-1);
    if (e.key === ' ' && currentVideo) {
        e.preventDefault();
        const video = document.getElementById('lightboxVideo');
        if (video.paused) video.play();
        else video.pause();
    }
});

function navigateVideo(direction) {
    const currentIndex = filteredVideos.findIndex(vid => vid.name === currentVideo);
    if (currentIndex === -1) return;
    
    const newIndex = (currentIndex + direction + filteredVideos.length) % filteredVideos.length;
    openLightbox(filteredVideos[newIndex].name);
}

// Initialize
document.addEventListener('DOMContentLoaded', function() {
    fetchVideoShareStatus();
    fetchVideos();
});
