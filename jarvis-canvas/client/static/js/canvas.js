/**
 * Jarvis Canvas - Canvas Pages JavaScript
 */

// State
let pages = [];
let currentPage = null;
let editingPage = null;

// =========================================================================
// Sidebar Toggle (Mobile)
// =========================================================================

function toggleSidebar() {
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('sidebarOverlay');
    
    sidebar.classList.toggle('open');
    overlay.classList.toggle('active');
    
    // Prevent body scroll when sidebar is open
    document.body.style.overflow = sidebar.classList.contains('open') ? 'hidden' : '';
}

function closeSidebar() {
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('sidebarOverlay');
    
    sidebar.classList.remove('open');
    overlay.classList.remove('active');
    document.body.style.overflow = '';
}

// Configure marked
marked.setOptions({
    highlight: function(code, lang) {
        if (lang && hljs.getLanguage(lang)) {
            return hljs.highlight(code, { language: lang }).value;
        }
        return hljs.highlightAuto(code).value;
    },
    breaks: true,
    gfm: true
});

/**
 * Resolve stash:// URLs to API endpoints
 * Converts: stash://space_id/file_id -> /api/stash/space_id/file_id
 */
function resolveStashUrls(content) {
    if (!content) return content;
    // Match stash:// URLs in markdown image/link syntax and raw URLs
    return content.replace(/stash:\/\/([^)\s"']+)/g, '/api/stash/$1');
}

/**
 * Preserve literal approximation tildes like "~80C" while keeping markdown
 * strikethrough support for intentional "~~text~~" sequences.
 */
function preserveSingleTildes(content) {
    if (!content) return content;
    return content.replace(/(^|[^~])~(?=[^~])/g, '$1&#126;');
}

/**
 * Render markdown with stash URL resolution
 */
function renderMarkdown(content) {
    // First resolve stash URLs, then parse markdown
    const resolved = preserveSingleTildes(resolveStashUrls(content));
    return DOMPurify.sanitize(marked.parse(resolved));
}

// API Functions
async function fetchPages() {
    try {
        const res = await fetch('/api/pages');
        pages = await res.json();
        lastPagesHash = computePagesHash(pages);
        renderSidebar();
        document.getElementById('pageCount').textContent = `${pages.length} page${pages.length !== 1 ? 's' : ''}`;
        
        if (pages.length === 0) {
            showEmptyState();
        } else if (!currentPage) {
            // Show most recent page
            selectPage(pages[0].id);
        }
    } catch (err) {
        showToast('Failed to load pages', 'error');
    }
}

async function deletePage(id) {
    if (!confirm('Delete this page? This cannot be undone.')) return;
    
    try {
        await fetch(`/api/pages/${id}`, { method: 'DELETE' });
        showToast('Page deleted', 'success');
        currentPage = null;
        fetchPages();
        showEmptyState();
    } catch (err) {
        showToast('Failed to delete page', 'error');
    }
}

async function togglePin(id) {
    const page = pages.find(p => p.id === id);
    if (!page) return;
    
    try {
        await fetch(`/api/pages/${id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ pinned: !page.pinned })
        });
        fetchPages();
    } catch (err) {
        showToast('Failed to update page', 'error');
    }
}

async function saveEdit() {
    if (!editingPage) return;
    
    const title = document.getElementById('editTitle').value;
    const tags = document.getElementById('editTags').value.split(',').map(t => t.trim()).filter(Boolean);
    const content = document.getElementById('editContent').value;
    
    try {
        await fetch(`/api/pages/${editingPage}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title, tags, content })
        });
        showToast('Page updated', 'success');
        closeEditModal();
        fetchPages();
        if (currentPage === editingPage) {
            selectPage(editingPage);
        }
    } catch (err) {
        showToast('Failed to save changes', 'error');
    }
}

// Print function
function printPage() {
    window.print();
}

// Download page function
function downloadPage(id, format = 'json') {
    const url = `/api/pages/${id}/download?format=${format}`;
    const link = document.createElement('a');
    link.href = url;
    link.download = ''; // Let server set filename
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    showToast('Downloading page...', 'success');
}

// Upload modal functions
let uploadData = null;

function openUploadModal() {
    uploadData = null;
    document.getElementById('uploadFile').value = '';
    document.getElementById('uploadPreview').classList.remove('active');
    document.getElementById('uploadSubmitBtn').disabled = true;
    document.getElementById('uploadForceNew').checked = false;
    document.getElementById('uploadModal').classList.add('active');
}

function closeUploadModal() {
    uploadData = null;
    document.getElementById('uploadModal').classList.remove('active');
}

function handleFileSelect(event) {
    const file = event.target.files[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = function(e) {
        try {
            uploadData = JSON.parse(e.target.result);
            
            // Show preview
            document.getElementById('uploadPreviewTitle').textContent = uploadData.title || 'Untitled';
            const tags = uploadData.tags ? uploadData.tags.join(', ') : 'none';
            const contentLen = uploadData.content ? uploadData.content.length : 0;
            document.getElementById('uploadPreviewInfo').textContent = 
                `Tags: ${tags} | Content: ${contentLen} characters`;
            document.getElementById('uploadPreview').classList.add('active');
            document.getElementById('uploadSubmitBtn').disabled = false;
        } catch (err) {
            showToast('Invalid JSON file', 'error');
            uploadData = null;
        }
    };
    reader.readAsText(file);
}

async function submitUpload() {
    if (!uploadData) return;

    const forceNew = document.getElementById('uploadForceNew').checked;
    if (forceNew) {
        uploadData.force_new = true;
    }

    try {
        const response = await fetch('/api/pages/upload', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(uploadData)
        });
        const result = await response.json();
        
        if (response.ok) {
            showToast(`Page ${result.action}!`, 'success');
            closeUploadModal();
            fetchPages();
            if (result.page && result.page.id) {
                selectPage(result.page.id);
            }
        } else {
            showToast(result.error || 'Upload failed', 'error');
        }
    } catch (err) {
        showToast('Failed to upload page', 'error');
    }
}

// Drag and drop support for upload
document.addEventListener('DOMContentLoaded', function() {
    const uploadArea = document.getElementById('uploadArea');
    if (uploadArea) {
        uploadArea.addEventListener('dragover', (e) => {
            e.preventDefault();
            uploadArea.classList.add('dragover');
        });
        uploadArea.addEventListener('dragleave', () => {
            uploadArea.classList.remove('dragover');
        });
        uploadArea.addEventListener('drop', (e) => {
            e.preventDefault();
            uploadArea.classList.remove('dragover');
            const file = e.dataTransfer.files[0];
            if (file && file.name.endsWith('.json')) {
                const input = document.getElementById('uploadFile');
                const dt = new DataTransfer();
                dt.items.add(file);
                input.files = dt.files;
                handleFileSelect({ target: input });
            } else {
                showToast('Please drop a JSON file', 'error');
            }
        });
    }
});

// Extract folder from title (e.g., "Phone Calls/2025-12-14" → "Phone Calls")
// Handles nested folders: "Workflows/Archive/bigsk1.com" → "Workflows/Archive"
// Ignores URLs: "Archive: https://example.com" → null (no folder)
// Smart boundary: stops splitting when a segment is too long to be a folder name,
// so titles containing "/" (e.g., "6 3/4 ft") don't create spurious folders.
function getFolder(title) {
    if (!title || !title.includes('/')) {
        return null;
    }
    
    // Skip if title contains a URL (http:// or https://)
    if (title.includes('://')) {
        return null;
    }
    
    const MAX_FOLDER_SEGMENT = 50;
    const parts = title.split('/');
    if (parts.length < 2) return null;
    
    // Walk segments: only treat short ones as folder names.
    // Once we hit a long segment, everything from there on is the page title.
    const folderParts = [];
    for (let i = 0; i < parts.length - 1; i++) {
        const segment = parts[i].trim();
        if (segment.length > MAX_FOLDER_SEGMENT) {
            break;
        }
        folderParts.push(segment);
    }
    
    return folderParts.length > 0 ? folderParts.join('/') : null;
}

// Get display title (everything after the folder path)
function getDisplayTitle(title) {
    if (!title) return title;
    
    const folder = getFolder(title);
    if (!folder) return title;
    
    // Return everything after the folder prefix
    return title.substring(folder.length + 1).trim();
}

// Track expanded folders
let expandedFolders = new Set();

function toggleFolder(folderName) {
    if (expandedFolders.has(folderName)) {
        expandedFolders.delete(folderName);
    } else {
        expandedFolders.add(folderName);
    }
    renderSidebar();
}

// =========================================================================
// Tree Builder - Parse flat page list into nested hierarchy
// =========================================================================

// Build a nested tree from flat pages array.
// Each node has _children (sub-folders) and _pages (leaf pages at that level).
// Pages with no folder path go into the root _pages array.
function buildTree(pages) {
    const tree = { _children: {}, _pages: [] };
    
    pages.forEach(page => {
        const folder = getFolder(page.title);
        if (!folder) {
            tree._pages.push(page);
            return;
        }
        
        // Split folder path into segments, skip empty parts
        const parts = folder.split('/').map(p => p.trim()).filter(p => p.length > 0);
        let current = tree;
        
        parts.forEach(part => {
            if (!current._children[part]) {
                current._children[part] = { _children: {}, _pages: [] };
            }
            current = current._children[part];
        });
        
        current._pages.push(page);
    });
    
    return tree;
}

// Count total pages under a tree node (recursive)
function countTreePages(node) {
    let count = node._pages.length;
    for (const child of Object.values(node._children)) {
        count += countTreePages(child);
    }
    return count;
}

// Check if any page under this node is the currently active page (recursive)
function hasActivePageInTree(node) {
    if (node._pages.some(p => p.id === currentPage)) return true;
    for (const child of Object.values(node._children)) {
        if (hasActivePageInTree(child)) return true;
    }
    return false;
}

// Auto-expand all ancestor folders of the currently active page
function autoExpandAncestors() {
    if (!currentPage) return;
    const page = pages.find(p => p.id === currentPage);
    if (!page) return;
    
    const folder = getFolder(page.title);
    if (!folder) return;
    
    const parts = folder.split('/').map(p => p.trim()).filter(p => p.length > 0);
    let path = '';
    parts.forEach((part, i) => {
        path = i === 0 ? part : path + '/' + part;
        expandedFolders.add(path);
    });
}

// Render a single tree node (folder) and its children recursively
function renderTreeNode(name, node, depth, path) {
    const totalPages = countTreePages(node);
    if (totalPages === 0) return '';
    
    const hasActive = hasActivePageInTree(node);
    
    // Auto-expand if this folder contains the active page
    if (hasActive) {
        expandedFolders.add(path);
    }
    
    const expanded = expandedFolders.has(path);
    const childNames = Object.keys(node._children).sort();
    
    let html = `
        <li class="folder-item ${expanded ? 'expanded' : ''} ${hasActive ? 'active' : ''}"
            onclick="toggleFolder('${escapeHtml(path)}')">
            <svg class="folder-icon" width="16" height="16" viewBox="0 0 16 16" fill="none">
                <path d="M6 3.5l4.5 4.5-4.5 4.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
            <span class="folder-name" title="${escapeHtml(path)}">${escapeHtml(name)}</span>
            <span class="folder-count">${totalPages}</span>
        </li>
        <ul class="tree-children ${expanded ? 'expanded' : ''}">
    `;
    
    // Render sub-folders first (sorted alphabetically)
    childNames.forEach(childName => {
        const childPath = path + '/' + childName;
        html += renderTreeNode(childName, node._children[childName], depth + 1, childPath);
    });
    
    // Render leaf pages in this folder
    node._pages.forEach(page => {
        html += renderPageItem(page, false, true);
    });
    
    html += '</ul>';
    return html;
}

// =========================================================================
// Render Functions
// =========================================================================

function renderSidebar() {
    const pinnedList = document.getElementById('pinnedList');
    const pinnedSection = document.getElementById('pinnedSection');
    const folderList = document.getElementById('folderList');
    const foldersSection = document.getElementById('foldersSection');
    const pageList = document.getElementById('pageList');
    
    const pinned = pages.filter(p => p.pinned);
    const unpinned = pages.filter(p => !p.pinned);
    
    // Show/hide pinned section
    pinnedSection.style.display = pinned.length > 0 ? 'block' : 'none';
    pinnedList.innerHTML = pinned.map(p => renderPageItem(p, true)).join('');
    
    // Build hierarchical tree from unpinned pages
    const tree = buildTree(unpinned);
    
    // Sort top-level folders alphabetically
    const sortedFolders = Object.keys(tree._children).sort();
    
    // Show/hide folders section
    foldersSection.style.display = sortedFolders.length > 0 ? 'block' : 'none';
    
    // Auto-expand ancestor folders of the active page
    autoExpandAncestors();
    
    // Render the tree recursively
    folderList.innerHTML = sortedFolders.map(folderName => {
        return renderTreeNode(folderName, tree._children[folderName], 0, folderName);
    }).join('');
    
    // Render pages without folders (root-level pages)
    pageList.innerHTML = tree._pages.map(p => renderPageItem(p, false)).join('');
}

function renderPageItem(page, isPinned, inFolder = false) {
    const icon = getPageIcon(page);
    const date = new Date(page.updated || page.created).toLocaleDateString();
    const activeClass = currentPage === page.id ? 'active' : '';
    const pinnedClass = isPinned ? 'pinned' : '';
    
    // Show shortened title if in folder
    const displayTitle = inFolder ? getDisplayTitle(page.title) : page.title;
    const fullTitle = page.title;
    
    return `
        <li class="page-item ${activeClass} ${pinnedClass}" onclick="event.stopPropagation(); selectPage('${page.id}')">
            <span class="page-icon">${icon}</span>
            <div class="page-info">
                <div class="page-title">${escapeHtml(displayTitle)}</div>
                <div class="page-meta">${date}</div>
            </div>
            <div class="tooltip">${escapeHtml(fullTitle)}</div>
        </li>
    `;
}

function getPageIcon(page) {
    const tags = page.tags || [];
    const title = (page.title || '').toLowerCase();
    
    // Check title-based icons first
    if (title.startsWith('phone calls/')) return '📞';
    if (title.startsWith('system prompt')) return '🧠';
    
    // Tag-based icons
    if (tags.includes('phone_call') || tags.includes('transcript')) return '📞';
    if (tags.includes('code') || tags.includes('script')) return '💻';
    if (tags.includes('research')) return '🔬';
    if (tags.includes('movies') || tags.includes('entertainment')) return '🎬';
    if (tags.includes('server') || tags.includes('network')) return '🖥️';
    if (tags.includes('api')) return '🔌';
    if (tags.includes('note')) return '📝';
    if (tags.includes('reference')) return '📚';
    if (tags.includes('evolution')) return '🧬';
    return '📄';
}

function selectPage(id) {
    currentPage = id;
    const page = pages.find(p => p.id === id);
    if (!page) return;
    
    closeSidebar(); // Close sidebar on mobile
    renderSidebar(); // Update active state
    document.getElementById('emptyState').style.display = 'none';
    
    const pageView = document.getElementById('pageView');
    pageView.style.display = 'block';
    
    const tagsHtml = (page.tags || []).map(t => `<span class="tag">${escapeHtml(t)}</span>`).join('');
    const sourceHtml = page.source_query ? `
        <div class="source-query">
            <div class="source-query-label">Source Query</div>
            <div class="source-query-text">"${escapeHtml(page.source_query)}"</div>
        </div>
    ` : '';
    
    const content = renderMarkdown(page.content || '');
    const created = new Date(page.created).toLocaleString();
    const updated = page.updated ? new Date(page.updated).toLocaleString() : null;
    
    // Build breadcrumb from folder path, show only leaf name as title
    const folder = getFolder(page.title);
    const displayTitle = getDisplayTitle(page.title);
    const breadcrumbHtml = folder ? `
        <div class="page-breadcrumb">${folder.split('/').map(s => `<span>${escapeHtml(s.trim())}</span>`).join('<span class="breadcrumb-sep">/</span>')}</div>
    ` : '';
    
    pageView.innerHTML = `
        <div class="page-header">
            <div class="page-header-top">
                <div class="page-title-block">
                    ${breadcrumbHtml}
                    <h1 class="page-view-title">${escapeHtml(displayTitle)}</h1>
                </div>
                <div class="page-header-actions">
                    <button class="btn btn-secondary btn-icon" onclick="togglePin('${page.id}')" title="${page.pinned ? 'Unpin' : 'Pin'}">
                        ${page.pinned ? '📌' : '📍'}
                    </button>
                    <button class="btn btn-secondary btn-icon" onclick="downloadPage('${page.id}')" title="Download">
                        📥
                    </button>
                    <button class="btn btn-secondary btn-icon" onclick="printPage()" title="Print">
                        🖨️
                    </button>
                    <button class="btn btn-secondary" onclick="openEditModal('${page.id}')">
                        ✏️ Edit
                    </button>
                    <button class="btn btn-danger btn-icon" onclick="deletePage('${page.id}')" title="Delete">
                        🗑️
                    </button>
                </div>
            </div>
            <div class="page-header-meta">
                <span>📅 Created: ${created}</span>
                ${updated ? `<span>✏️ Updated: ${updated}</span>` : ''}
            </div>
            ${tagsHtml ? `<div class="page-tags">${tagsHtml}</div>` : ''}
        </div>
        <div class="page-content">${content}</div>
        ${sourceHtml}
    `;
    
    // Re-highlight code blocks
    pageView.querySelectorAll('pre code').forEach(block => {
        hljs.highlightElement(block);
    });

    // Setup content interaction handlers
    setupImageHandlers();
    setupLinkHandlers();
}

function showEmptyState() {
    document.getElementById('emptyState').style.display = 'flex';
    document.getElementById('pageView').style.display = 'none';
}

function openEditModal(id) {
    editingPage = id;
    const page = pages.find(p => p.id === id);
    if (!page) return;
    
    document.getElementById('editTitle').value = page.title;
    document.getElementById('editTags').value = (page.tags || []).join(', ');
    document.getElementById('editContent').value = page.content || '';
    document.getElementById('editModal').classList.add('active');
}

function closeEditModal() {
    editingPage = null;
    document.getElementById('editModal').classList.remove('active');
}

// Search
function filterPages(query) {
    const q = query.toLowerCase();
    const filtered = pages.filter(p => 
        p.title.toLowerCase().includes(q) ||
        (p.content || '').toLowerCase().includes(q) ||
        (p.tags || []).some(t => t.toLowerCase().includes(q))
    );
    
    const pageList = document.getElementById('pageList');
    const pinnedList = document.getElementById('pinnedList');
    const foldersSection = document.getElementById('foldersSection');
    const pinnedSection = document.getElementById('pinnedSection');
    
    if (q) {
        // When searching, show flat results and hide tree/pinned sections
        pinnedSection.style.display = 'none';
        pinnedList.innerHTML = '';
        foldersSection.style.display = 'none';
        document.getElementById('folderList').innerHTML = '';
        pageList.innerHTML = filtered.map(p => renderPageItem(p, false)).join('');
    } else {
        renderSidebar();
    }
}

// Image Lightbox Functions
function openLightbox(src) {
    const lightbox = document.getElementById('imageLightbox');
    const img = document.getElementById('lightboxImage');
    img.src = src;
    lightbox.classList.add('active');
}

function closeLightbox() {
    document.getElementById('imageLightbox').classList.remove('active');
}

// Setup click handlers for images in content
function setupImageHandlers() {
    document.querySelectorAll('.page-content img').forEach(img => {
        img.onclick = (e) => {
            e.preventDefault();
            openLightbox(img.src);
        };
    });
}

// Keep canvas page open while following content links
function setupLinkHandlers() {
    document.querySelectorAll('.page-content a').forEach(link => {
        link.setAttribute('target', '_blank');
        link.setAttribute('rel', 'noopener noreferrer');
    });
}

// Utilities
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function showToast(message, type = 'success') {
    const container = document.getElementById('toastContainer');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerHTML = `
        <span>${type === 'success' ? '✅' : '❌'}</span>
        <span>${message}</span>
    `;
    container.appendChild(toast);
    setTimeout(() => toast.remove(), 3000);
}

// Event Listeners
document.addEventListener('DOMContentLoaded', function() {
    const searchInput = document.getElementById('searchInput');
    if (searchInput) {
        searchInput.addEventListener('input', (e) => {
            filterPages(e.target.value);
        });
    }
    
    // Initial load
    fetchPages();
});

document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        document.getElementById('searchInput').focus();
    }
    if (e.key === 'Escape') {
        closeEditModal();
        closeUploadModal();
    }
});

// Polling for updates (live reload with hash-based comparison)
// Detects adds, deletes, renames, and moves (not just count changes)
let lastPagesHash = '';

function computePagesHash(pageList) {
    return pageList.map(p => p.id + ':' + p.title + ':' + (p.pinned ? '1' : '0')).join('|');
}

setInterval(async () => {
    try {
        const res = await fetch('/api/pages');
        const newPages = await res.json();
        const newHash = computePagesHash(newPages);
        if (newHash !== lastPagesHash) {
            lastPagesHash = newHash;
            pages = newPages;
            renderSidebar();
            document.getElementById('pageCount').textContent = `${pages.length} page${pages.length !== 1 ? 's' : ''}`;
            if (pages.length > 0 && !currentPage) {
                selectPage(pages[0].id);
            }
        }
    } catch (err) {}
}, 2000);
