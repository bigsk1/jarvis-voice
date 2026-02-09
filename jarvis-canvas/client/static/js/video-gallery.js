/**
 * Jarvis Canvas - Video Gallery JavaScript
 */

let videos = [];
let filteredVideos = [];
let currentVideo = null;

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
                ${provider ? `<span class="video-provider">${provider}</span>` : ''}
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
        openLightbox(filteredVideos[index].name);
    }
}

function downloadByIndex(index) {
    if (index >= 0 && index < filteredVideos.length) {
        downloadDirect(filteredVideos[index].name);
    }
}

function deleteByIndex(index) {
    if (index >= 0 && index < filteredVideos.length) {
        deleteVideo(filteredVideos[index].name);
    }
}

function openLightbox(filename) {
    currentVideo = filename;
    const video = document.getElementById('lightboxVideo');
    video.src = `/api/gallery/videos/${encodeURIComponent(filename)}`;
    document.getElementById('lightboxFilename').textContent = filename;
    document.getElementById('videoLightbox').classList.add('active');
    document.body.style.overflow = 'hidden';
    video.play().catch(() => {});
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

async function deleteVideo(filename) {
    if (!confirm(`Delete "${filename}"?\n\nThis cannot be undone.`)) return;
    
    try {
        const response = await fetch(`/api/gallery/videos/${encodeURIComponent(filename)}`, {
            method: 'DELETE'
        });
        
        if (response.ok) {
            showToast('Video deleted');
            refreshGallery();
        } else {
            const data = await response.json();
            showToast(data.error || 'Failed to delete', 'error');
        }
    } catch (err) {
        showToast('Failed to delete video', 'error');
    }
}

function deleteFromLightbox() {
    if (currentVideo) {
        closeLightbox();
        deleteVideo(currentVideo);
    }
}

function refreshGallery() {
    fetchVideos();
}

function showToast(message, type = 'success') {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.className = 'toast active' + (type === 'error' ? ' error' : '');
    setTimeout(() => toast.classList.remove('active'), 3000);
}

// Keyboard shortcuts
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeLightbox();
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
    fetchVideos();
});
