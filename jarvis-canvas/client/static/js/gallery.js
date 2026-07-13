/**
 * Jarvis Canvas - Image Gallery JavaScript
 */

let images = [];
let filteredImages = [];
let currentImage = null;
let refreshInProgress = false;

async function fetchImages() {
    try {
        const response = await fetch('/api/gallery/images');
        const data = await response.json();
        images = data.images || [];
        document.getElementById('imageCount').textContent = `${images.length} images`;
        document.getElementById('totalSize').textContent = formatSize(data.total_size || 0);
        filterImages();
    } catch (err) {
        console.error('Failed to fetch images:', err);
        showToast('Failed to load images', 'error');
    }
}

function filterImages() {
    const search = document.getElementById('searchInput').value.toLowerCase();
    const providerFilter = document.getElementById('providerFilter').value;
    const favoriteFilter = document.getElementById('favoriteFilter')?.value || 'all';
    
    filteredImages = images.filter(img => {
        const name = img.name.toLowerCase();
        const imgProvider = (img.provider || detectProvider(img.name) || '').toLowerCase();
        
        // Text search (name or provider)
        if (search && !name.includes(search) && !imgProvider.includes(search)) {
            return false;
        }
        
        // Provider filter
        if (providerFilter !== 'all') {
            if (!imgProvider.includes(providerFilter)) {
                return false;
            }
        }

        if (favoriteFilter === 'favorites' && !img.favorite) {
            return false;
        }
        
        return true;
    });
    sortImages();
}

function sortImages() {
    const sort = document.getElementById('sortSelect').value;
    
    filteredImages.sort((a, b) => {
        switch (sort) {
            case 'date-desc': return new Date(b.modified) - new Date(a.modified);
            case 'date-asc': return new Date(a.modified) - new Date(b.modified);
            case 'name-asc': return a.name.localeCompare(b.name);
            case 'name-desc': return b.name.localeCompare(a.name);
            case 'size-desc': return b.size - a.size;
            case 'size-asc': return a.size - b.size;
            case 'cdn-desc':
                return Number(Boolean(b.cdn_cached)) - Number(Boolean(a.cdn_cached))
                    || new Date(b.modified) - new Date(a.modified);
            case 'cdn-asc':
                return Number(Boolean(a.cdn_cached)) - Number(Boolean(b.cdn_cached))
                    || new Date(b.modified) - new Date(a.modified);
            default: return 0;
        }
    });
    
    renderGallery();
}

function renderGallery() {
    const gallery = document.getElementById('gallery');
    const emptyState = document.getElementById('emptyState');
    
    if (filteredImages.length === 0) {
        gallery.innerHTML = '';
        emptyState.style.display = 'block';
        return;
    }
    
    emptyState.style.display = 'none';
    
    gallery.innerHTML = filteredImages.map((img, index) => {
        // Use provider from API if available, otherwise detect from filename
        const provider = img.provider || detectProvider(img.name);
        const favorite = Boolean(img.favorite);
        
        return `
        <div class="image-card${favorite ? ' is-favorite' : ''}" data-index="${index}">
            <div class="image-wrapper" onclick="openLightboxByIndex(${index})">
                <img src="/api/gallery/images/${encodeURIComponent(img.name)}" 
                     alt="${escapeHtml(img.name)}" 
                     loading="lazy">
                ${provider ? `<span class="image-provider">${provider}</span>` : ''}
            </div>
            <div class="image-info">
                <div class="image-name" title="${escapeHtml(img.name)}">${escapeHtml(formatImageName(img.name))}</div>
                <div class="image-meta">
                    <span>${formatDate(img.modified)}</span>
                    <span>${formatSize(img.size)}</span>
                </div>
                <div class="image-actions">
                    <div class="image-actions-left">
                        <button class="btn btn-favorite${favorite ? ' is-favorite' : ''}" onclick="event.stopPropagation(); toggleFavoriteByIndex(${index}, this)" title="${favorite ? 'Remove from favorites' : 'Add to favorites'}" aria-pressed="${favorite ? 'true' : 'false'}">${favorite ? '♥' : '♡'}</button>
                        <button class="btn btn-primary" onclick="event.stopPropagation(); downloadByIndex(${index})" title="Download image">⬇️</button>
                        <button class="btn btn-secondary" onclick="event.stopPropagation(); getCdnUrlByIndex(${index}, this)" title="${img.cdn_cached ? 'Copy cached CDN URL' : 'Create CDN URL'}">🔗</button>
                        <button class="btn btn-accent" onclick="event.stopPropagation(); sendImageToJarvisWebByIndex(${index})" title="Send to Jarvis Web for video">🎬</button>
                    </div>
                    <div class="image-actions-right">
                        <button class="btn btn-danger" onclick="event.stopPropagation(); deleteByIndex(${index})" title="Delete image">🗑️</button>
                    </div>
                </div>
            </div>
        </div>
    `}).join('');
}

function detectProvider(name) {
    // Detect provider from filename patterns (fallback when no stash metadata)
    const lower = name.toLowerCase();
    
    if (lower.includes('xai') || lower.includes('grok')) return 'xAI';
    if (lower.includes('gemini')) return 'Gemini';
    if (lower.includes('openai') || lower.includes('dall-e') || lower.includes('dalle')) return 'OpenAI';
    if (lower.includes('stability') || lower.includes('stable')) return 'Stability';
    
    return null;
}

function formatImageName(name) {
    // Clean up generated image names for display
    return name
        .replace(/^generated_/, '')
        .replace(/_\d{8}_\d{6}\.(jpg|jpeg|png|webp|gif)$/i, '')
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

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function openLightboxByIndex(index) {
    if (index >= 0 && index < filteredImages.length) {
        const name = filteredImages[index].name;
        if (name) openLightbox(name);
    }
}

function downloadByIndex(index) {
    if (index >= 0 && index < filteredImages.length) {
        downloadDirect(filteredImages[index].name);
    }
}

function deleteByIndex(index) {
    if (index >= 0 && index < filteredImages.length) {
        deleteImage(filteredImages[index].name);
    }
}

function getCdnUrlByIndex(index, btn = null) {
    if (index >= 0 && index < filteredImages.length) {
        const img = filteredImages[index];
        if (confirmCdnUploadIfNeeded(img)) {
            getCdnUrl(img.name, btn);
        }
    }
}

function findImageByName(filename) {
    return images.find(item => item.name === filename) || null;
}

function confirmCdnUploadIfNeeded(imgOrFilename) {
    const img = typeof imgOrFilename === 'string' ? findImageByName(imgOrFilename) : imgOrFilename;
    if (img && img.cdn_cached) return true;

    return window.confirm(
        'Create a public Cloudflare CDN URL for this image?\n\n' +
        'If this image is not already cached, Jarvis will upload it to Cloudflare Images. ' +
        'Anyone with the resulting URL can open it.\n\n' +
        'Continue?'
    );
}

function markCdnCached(filename) {
    const image = findImageByName(filename);
    if (!image) return false;
    image.cdn_cached = true;
    return true;
}

function formatCdnError(error) {
    const message = String(error || 'Failed to get URL');
    if (/CLOUDFLARE_(API_TOKEN|ACCOUNT_ID) not configured/i.test(message)) {
        return 'Cloudflare CDN is not configured for this Jarvis mode/env. Add CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID to the active env file.';
    }
    return message;
}

function toggleFavoriteByIndex(index, btn = null) {
    if (index >= 0 && index < filteredImages.length) {
        const img = filteredImages[index];
        toggleFavorite(img.name, !img.favorite, btn);
    }
}

function toggleFavoriteCurrent() {
    if (!currentImage) return;
    const img = images.find(item => item.name === currentImage);
    toggleFavorite(currentImage, !(img && img.favorite), document.getElementById('lightboxFavoriteBtn'));
}

function updateImageFavoriteState(filename, favorite, favoritedAt) {
    const image = images.find(item => item.name === filename);
    if (image) {
        image.favorite = favorite;
        image.favorited_at = favoritedAt || null;
    }
}

function updateLightboxFavoriteButton(filename) {
    const btn = document.getElementById('lightboxFavoriteBtn');
    if (!btn || !filename) return;
    const image = images.find(item => item.name === filename);
    const favorite = Boolean(image && image.favorite);
    btn.classList.toggle('is-favorite', favorite);
    btn.setAttribute('aria-pressed', favorite ? 'true' : 'false');
    btn.textContent = favorite ? '♥ Favorite' : '♡ Favorite';
    btn.title = favorite ? 'Remove from favorites' : 'Add to favorites';
}

async function toggleFavorite(filename, favorite, btn = null) {
    if (!filename) return;
    if (btn) btn.disabled = true;

    try {
        const response = await fetch(`/api/gallery/images/${encodeURIComponent(filename)}/favorite`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ favorite })
        });
        const data = await response.json();

        if (!response.ok || !data.ok) {
            throw new Error(data.error || 'Failed to update favorite');
        }

        updateImageFavoriteState(filename, Boolean(data.favorite), data.favorited_at);
        if (currentImage === filename) {
            updateLightboxFavoriteButton(filename);
        }
        filterImages();
        showToast(data.favorite ? 'Added to favorites' : 'Removed from favorites');
    } catch (err) {
        showToast(err.message || 'Favorite update failed', 'error');
    } finally {
        if (btn) btn.disabled = false;
    }
}

async function getCdnUrl(filename, btn = null) {
    if (btn) {
        btn.disabled = true;
        btn.textContent = '⏳';
    }
    
    try {
        const response = await fetch(`/api/gallery/images/${encodeURIComponent(filename)}/cdn-url`);
        const data = await response.json();
        
        if (data.ok && data.url) {
            if (markCdnCached(filename)) sortImages();
            // Copy to clipboard (with fallback for non-HTTPS)
            const copied = await copyToClipboard(data.url);
            
            // Show success message
            const msg = data.cached ? 'URL copied (cached)' : 'Uploaded! URL copied';
            if (copied) {
                showToast(`✅ ${msg}`, 'success');
            } else {
                // Clipboard failed but URL is valid - show it
                showToast(`✅ ${data.cached ? 'Cached' : 'Uploaded'} - see console for URL`, 'success');
            }
            
            // Always log to console for easy access
            console.log(`CDN URL for ${filename}:`, data.url);
        } else {
            showToast(`❌ ${formatCdnError(data.error)}`, 'error');
        }
    } catch (err) {
        showToast(`❌ Error: ${err.message}`, 'error');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.textContent = '🔗';
        }
    }
}

async function copyToClipboard(text) {
    const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) || 
              (navigator.userAgent.includes('Mac') && navigator.maxTouchPoints > 1);
    
    // Try modern API first
    if (navigator.clipboard && navigator.clipboard.writeText) {
        try {
            await navigator.clipboard.writeText(text);
            return true;
        } catch (e) {
            // Fall through to fallback
        }
    }
    
    // iOS fallback: Use Web Share API to share URL (has "Copy" option)
    if (isIOS && navigator.share) {
        try {
            await navigator.share({ url: text });
            return true;  // User used share sheet (may have copied)
        } catch (e) {
            if (e.name === 'AbortError') return false;  // User cancelled
            // Fall through to prompt
        }
    }
    
    // Fallback for non-HTTPS contexts (desktop)
    try {
        const textarea = document.createElement('textarea');
        textarea.value = text;
        textarea.style.position = 'fixed';
        textarea.style.left = '-9999px';
        document.body.appendChild(textarea);
        textarea.select();
        const success = document.execCommand('copy');
        document.body.removeChild(textarea);
        if (success) return true;
    } catch (e) {
        // Fall through to prompt
    }
    
    // Final fallback: Show prompt where user can manually copy
    if (isIOS) {
        // iOS: Use prompt() which allows native text selection/copy
        window.prompt('Copy this URL:', text);
        return true;  // Assume user copied from prompt
    }
    
    console.log('CDN URL:', text);
    return false;
}

function showToast(message, type = 'success') {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.className = 'toast active' + (type === 'error' ? ' error' : '');
    setTimeout(() => toast.classList.remove('active'), 3000);
}

function openLightbox(filename) {
    if (!filename || filename === 'null' || filename === 'undefined') return;
    currentImage = filename;
    document.getElementById('lightboxImage').src = `/api/gallery/images/${encodeURIComponent(filename)}`;
    document.getElementById('lightboxFilename').textContent = filename;
    updateLightboxFavoriteButton(filename);
    document.getElementById('lightbox').classList.add('active');
    document.body.style.overflow = 'hidden';
}

function closeLightbox(event) {
    if (event && event.target !== document.getElementById('lightbox')) return;
    document.getElementById('lightbox').classList.remove('active');
    document.body.style.overflow = '';
    currentImage = null;
}

function downloadImage() {
    if (currentImage) downloadDirect(currentImage);
}

async function downloadDirect(filename) {
    // Use download endpoint with Content-Disposition header
    const url = `/api/gallery/images/${encodeURIComponent(filename)}/download`;
    const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) || 
              (navigator.userAgent.includes('Mac') && navigator.maxTouchPoints > 1);
    
    try {
        showToast('Preparing image...');
        const response = await fetch(url);
        if (!response.ok) throw new Error('Network response was not ok');
        
        const blob = await response.blob();
        // Determine proper extension and mime type
        const ext = filename.split('.').pop()?.toLowerCase() || 'png';
        const mimeMap = { 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png', 'webp': 'image/webp', 'gif': 'image/gif' };
        const mimeType = mimeMap[ext] || blob.type || 'image/png';
        const file = new File([blob], filename, { type: mimeType });

        if (isIOS && navigator.canShare && navigator.canShare({ files: [file] })) {
            // CRITICAL: Only pass 'files'. Adding title/text breaks "Save Image" option.
            await navigator.share({ files: [file] });
            showToast('Done!');
        } else {
            // Desktop and fallback
            const blobUrl = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = blobUrl;
            a.download = filename;
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

async function deleteImage(filename) {
    if (!filename || filename === 'null' || filename === 'undefined') {
        showToast('Cannot delete: no image selected', 'error');
        return;
    }
    if (!confirm(`Delete "${filename}"?\n\nThis cannot be undone.`)) return;
    
    try {
        const response = await fetch(`/api/gallery/images/${encodeURIComponent(filename)}`, {
            method: 'DELETE'
        });
        
        if (response.ok) {
            showToast('Image deleted');
            refreshGallery();
        } else {
            const data = await response.json();
            showToast(data.error || 'Failed to delete', 'error');
        }
    } catch (err) {
        showToast('Failed to delete image', 'error');
    }
}

function deleteFromLightbox() {
    const filename = currentImage || document.getElementById('lightboxFilename')?.textContent?.trim();
    if (filename && filename !== 'null') {
        closeLightbox();
        deleteImage(filename);
    } else {
        showToast('Cannot delete: no image selected', 'error');
    }
}

async function getCdnUrlFromLightbox() {
    if (currentImage) {
        if (!confirmCdnUploadIfNeeded(currentImage)) return;
        const btn = document.getElementById('lightboxCdnBtn');
        if (btn) {
            btn.disabled = true;
            btn.textContent = '⏳ Uploading...';
        }
        
        try {
            const response = await fetch(`/api/gallery/images/${encodeURIComponent(currentImage)}/cdn-url`);
            const data = await response.json();
            
            if (data.ok && data.url) {
                if (markCdnCached(currentImage)) sortImages();
                const copied = await copyToClipboard(data.url);
                const msg = data.cached ? 'URL copied!' : 'Uploaded & copied!';
                if (copied) {
                    showToast(`✅ ${msg}`, 'success');
                } else {
                    showToast(`✅ ${data.cached ? 'Cached' : 'Uploaded'} - see console`, 'success');
                }
                console.log(`CDN URL for ${currentImage}:`, data.url);
            } else {
                showToast(`❌ ${formatCdnError(data.error || 'Failed')}`, 'error');
            }
        } catch (err) {
            showToast(`❌ ${err.message}`, 'error');
        } finally {
            if (btn) {
                btn.disabled = false;
                btn.textContent = '🔗 Get URL';
            }
        }
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
        await fetchImages();
    } finally {
        refreshInProgress = false;
        setRefreshLoading(false);
    }
}

// Keyboard shortcuts
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        closeLightbox();
    }
    if (e.key === 'ArrowRight' && currentImage) navigateImage(1);
    if (e.key === 'ArrowLeft' && currentImage) navigateImage(-1);
});

function navigateImage(direction) {
    const currentIndex = filteredImages.findIndex(img => img.name === currentImage);
    if (currentIndex === -1) return;
    
    const newIndex = (currentIndex + direction + filteredImages.length) % filteredImages.length;
    openLightbox(filteredImages[newIndex].name);
}

// ============ Jarvis Web Media Handoff ============

function buildJarvisWebMediaHandoffUrl(filename, mediaType = 'image', action = 'video') {
    const url = new URL(window.location.href);
    url.port = '5001';
    url.pathname = '/';
    url.search = '';
    url.hash = '';
    url.searchParams.set('media_handoff', mediaType);
    url.searchParams.set('media_filename', filename);
    url.searchParams.set('media_action', action);
    return url.toString();
}

function sendImageToJarvisWeb(filename) {
    if (!filename || filename === 'null' || filename === 'undefined') {
        showToast('Cannot send: no image selected', 'error');
        return;
    }

    window.open(buildJarvisWebMediaHandoffUrl(filename), '_blank', 'noopener');
    showToast('Opened image in a new Jarvis Web conversation', 'success');
}

function sendImageToJarvisWebByIndex(index) {
    if (index >= 0 && index < filteredImages.length) {
        sendImageToJarvisWeb(filteredImages[index].name);
    }
}

function sendCurrentImageToJarvisWeb() {
    const filename = currentImage || document.getElementById('lightboxFilename')?.textContent?.trim();
    if (!filename || filename === 'null' || filename === 'undefined') {
        showToast('Cannot send: no image selected', 'error');
        return;
    }

    closeLightbox();
    sendImageToJarvisWeb(filename);
}

// Initialize
document.addEventListener('DOMContentLoaded', function() {
    fetchImages();
});
