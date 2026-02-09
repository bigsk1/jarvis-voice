/**
 * Jarvis Canvas - Image Gallery JavaScript
 */

let images = [];
let filteredImages = [];
let videoModalImage = null;
let currentImage = null;

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
        
        return `
        <div class="image-card" data-index="${index}">
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
                        <button class="btn btn-primary" onclick="event.stopPropagation(); downloadByIndex(${index})">⬇️</button>
                        <button class="btn btn-secondary" onclick="event.stopPropagation(); getCdnUrlByIndex(${index})" title="Get CDN URL">🔗</button>
                        <button class="btn btn-accent" onclick="event.stopPropagation(); openVideoModalByIndex(${index})" title="Convert to Video">🎬</button>
                    </div>
                    <div class="image-actions-right">
                        <button class="btn btn-danger" onclick="event.stopPropagation(); deleteByIndex(${index})">🗑️</button>
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
        openLightbox(filteredImages[index].name);
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

function getCdnUrlByIndex(index) {
    if (index >= 0 && index < filteredImages.length) {
        getCdnUrl(filteredImages[index].name);
    }
}

async function getCdnUrl(filename) {
    const btn = event ? event.target : null;
    if (btn) {
        btn.disabled = true;
        btn.textContent = '⏳';
    }
    
    try {
        const response = await fetch(`/api/gallery/images/${encodeURIComponent(filename)}/cdn-url`);
        const data = await response.json();
        
        if (data.ok && data.url) {
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
            showToast(`❌ ${data.error || 'Failed to get URL'}`, 'error');
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
    // Try modern API first
    if (navigator.clipboard && navigator.clipboard.writeText) {
        try {
            await navigator.clipboard.writeText(text);
            return true;
        } catch (e) {
            // Fall through to fallback
        }
    }
    
    // Fallback for non-HTTPS contexts
    try {
        const textarea = document.createElement('textarea');
        textarea.value = text;
        textarea.style.position = 'fixed';
        textarea.style.left = '-9999px';
        document.body.appendChild(textarea);
        textarea.select();
        const success = document.execCommand('copy');
        document.body.removeChild(textarea);
        return success;
    } catch (e) {
        console.error('Clipboard fallback failed:', e);
        return false;
    }
}

function showToast(message, type = 'success') {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.className = 'toast active' + (type === 'error' ? ' error' : '');
    setTimeout(() => toast.classList.remove('active'), 3000);
}

function openLightbox(filename) {
    currentImage = filename;
    document.getElementById('lightboxImage').src = `/api/gallery/images/${encodeURIComponent(filename)}`;
    document.getElementById('lightboxFilename').textContent = filename;
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
    if (currentImage) {
        closeLightbox();
        deleteImage(currentImage);
    }
}

async function getCdnUrlFromLightbox() {
    if (currentImage) {
        const btn = document.getElementById('lightboxCdnBtn');
        if (btn) {
            btn.disabled = true;
            btn.textContent = '⏳ Uploading...';
        }
        
        try {
            const response = await fetch(`/api/gallery/images/${encodeURIComponent(currentImage)}/cdn-url`);
            const data = await response.json();
            
            if (data.ok && data.url) {
                const copied = await copyToClipboard(data.url);
                const msg = data.cached ? 'URL copied!' : 'Uploaded & copied!';
                if (copied) {
                    showToast(`✅ ${msg}`, 'success');
                } else {
                    showToast(`✅ ${data.cached ? 'Cached' : 'Uploaded'} - see console`, 'success');
                }
                console.log(`CDN URL for ${currentImage}:`, data.url);
            } else {
                showToast(`❌ ${data.error || 'Failed'}`, 'error');
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

function refreshGallery() {
    fetchImages();
}

// Keyboard shortcuts
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        closeLightbox();
        closeVideoModal();
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

// ============ Video Generation Modal ============

function openVideoModalByIndex(index) {
    const img = filteredImages[index];
    if (img) openVideoModal(img.name);
}

function openVideoModalFromLightbox() {
    if (currentImage) {
        closeLightbox();
        openVideoModal(currentImage);
    }
}

function openVideoModal(filename) {
    videoModalImage = filename;
    document.getElementById('videoModalPreview').src = `/api/gallery/images/${encodeURIComponent(filename)}`;
    document.getElementById('videoPrompt').value = '';
    document.getElementById('videoModalForm').style.display = 'block';
    document.getElementById('videoProgress').classList.remove('active');
    document.getElementById('videoModal').classList.add('active');
    document.body.style.overflow = 'hidden';
    
    // Set default aspect ratio based on image (could be enhanced to detect actual ratio)
    document.getElementById('videoAspect').value = '16:9';
    updateVideoOptions();
}

function closeVideoModal() {
    document.getElementById('videoModal').classList.remove('active');
    document.body.style.overflow = '';
    videoModalImage = null;
}

function updateVideoOptions() {
    const provider = document.getElementById('videoProvider').value;
    const durationSelect = document.getElementById('videoDuration');
    const resolutionSelect = document.getElementById('videoResolution');
    const aspectSelect = document.getElementById('videoAspect');
    
    // Clear and rebuild duration options based on provider
    durationSelect.innerHTML = '';
    
    if (provider === 'openai') {
        // OpenAI Sora supports 4, 8, or 12 seconds
        ['4', '8', '12'].forEach(d => {
            const opt = document.createElement('option');
            opt.value = d;
            opt.text = d + ' seconds';
            durationSelect.appendChild(opt);
        });
        durationSelect.value = '8';
        
        // Sora supports 720p and 1080p (1080p only with sora-2-pro)
        resolutionSelect.innerHTML = `
            <option value="720p">720p (HD) - $0.10/s</option>
            <option value="1080p">1080p (Full HD) - $0.30-0.50/s</option>
        `;
        
        // Sora only supports 2 aspect ratios
        aspectSelect.innerHTML = `
            <option value="16:9">16:9 (Landscape)</option>
            <option value="9:16">9:16 (Portrait)</option>
        `;
    } else if (provider === 'gemini') {
        // Gemini only supports 4, 6, or 8 seconds
        ['4', '6', '8'].forEach(d => {
            const opt = document.createElement('option');
            opt.value = d;
            opt.text = d + ' seconds';
            durationSelect.appendChild(opt);
        });
        durationSelect.value = '8';
        
        // Gemini supports higher resolutions
        resolutionSelect.innerHTML = `
            <option value="720p">720p (HD)</option>
            <option value="1080p">1080p (Full HD) - 8s only</option>
            <option value="4k">4K (Ultra HD) - 8s only</option>
        `;
        
        // Gemini only supports 2 aspect ratios
        aspectSelect.innerHTML = `
            <option value="16:9">16:9 (Landscape)</option>
            <option value="9:16">9:16 (Portrait)</option>
        `;
    } else {
        // xAI supports 1-15 seconds
        ['5', '8', '10', '12', '15'].forEach(d => {
            const opt = document.createElement('option');
            opt.value = d;
            opt.text = d + ' seconds';
            durationSelect.appendChild(opt);
        });
        durationSelect.value = '5';
        
        // xAI supports 720p and 480p
        resolutionSelect.innerHTML = `
            <option value="720p">720p (HD)</option>
            <option value="480p">480p (SD)</option>
        `;
        
        // xAI supports more aspect ratios
        aspectSelect.innerHTML = `
            <option value="16:9">16:9 (Landscape)</option>
            <option value="9:16">9:16 (Portrait)</option>
            <option value="1:1">1:1 (Square)</option>
            <option value="4:3">4:3 (Classic)</option>
            <option value="3:2">3:2 (Photo)</option>
        `;
    }
}

async function generateVideo() {
    if (!videoModalImage) return;
    
    const prompt = document.getElementById('videoPrompt').value.trim();
    if (!prompt) {
        showToast('Please describe how the image should animate', 'error');
        return;
    }
    
    const provider = document.getElementById('videoProvider').value;
    const duration = parseInt(document.getElementById('videoDuration').value);
    const aspect = document.getElementById('videoAspect').value;
    const resolution = document.getElementById('videoResolution').value;
    
    // Show progress
    document.getElementById('videoModalForm').style.display = 'none';
    document.getElementById('videoProgress').classList.add('active');
    const providerName = provider === 'openai' ? 'OpenAI Sora' : provider === 'gemini' ? 'Gemini Veo' : 'xAI Grok';
    document.getElementById('videoProgressStatus').textContent = `Using ${providerName}...`;
    
    try {
        const response = await fetch(`/api/gallery/images/${encodeURIComponent(videoModalImage)}/to-video`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                prompt: prompt,
                provider: provider,
                duration: duration,
                aspect_ratio: aspect,
                resolution: resolution
            })
        });
        
        const data = await response.json();
        
        if (data.ok) {
            showToast('✅ Video generated! Check /video-gallery', 'success');
            closeVideoModal();
            
            // Open video gallery in new tab if available
            if (data.video_path) {
                console.log('Video saved to:', data.video_path);
            }
        } else {
            showToast(`❌ ${data.error || 'Video generation failed'}`, 'error');
            // Show form again
            document.getElementById('videoModalForm').style.display = 'block';
            document.getElementById('videoProgress').classList.remove('active');
        }
    } catch (err) {
        console.error('Video generation error:', err);
        showToast(`❌ ${err.message || 'Failed to generate video'}`, 'error');
        // Show form again
        document.getElementById('videoModalForm').style.display = 'block';
        document.getElementById('videoProgress').classList.remove('active');
    }
}

// Initialize
document.addEventListener('DOMContentLoaded', function() {
    fetchImages();
});
