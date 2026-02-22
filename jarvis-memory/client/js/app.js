/**
 * Jarvis Memory Browser - Main Application
 */

// State
let currentTab = 'memories';
let currentCategory = null;
let memories = [];
let categories = [];
let conversations = [];
let intelFiles = [];
let searchQuery = '';
let editingMemory = null;
let editingFile = null;

// Search placeholders per tab
const SEARCH_PLACEHOLDERS = {
  memories: 'Search memories (FTS5)...',
  intel: 'Search intel files...',
  conversations: 'Search conversations...',
  stats: 'Search...'
};

// =========================================================================
// Initialization
// =========================================================================

document.addEventListener('DOMContentLoaded', async () => {
  // Initialize mode from URL or localStorage
  const urlParams = new URLSearchParams(window.location.search);
  const savedMode = localStorage.getItem('jarvis-memory-mode') || 'cloud';
  const mode = urlParams.get('mode') || savedMode;
  
  document.getElementById('modeSelect').value = mode;
  api.setMode(mode);
  
  // Set up event listeners
  setupEventListeners();
  
  // Load initial data
  await loadData();
});

function setupEventListeners() {
  // Mode selector
  document.getElementById('modeSelect').addEventListener('change', async (e) => {
    const mode = e.target.value;
    api.setMode(mode);
    localStorage.setItem('jarvis-memory-mode', mode);
    await loadData();
  });
  
  // Hamburger menu toggle
  document.getElementById('hamburgerBtn')?.addEventListener('click', toggleSidebar);
  document.getElementById('sidebarClose')?.addEventListener('click', closeSidebar);
  document.getElementById('sidebarOverlay')?.addEventListener('click', closeSidebar);
  
  // Nav tabs (both desktop and mobile)
  document.querySelectorAll('.nav-tab').forEach(tab => {
    tab.addEventListener('click', () => {
      switchTab(tab.dataset.tab);
      closeSidebar(); // Close sidebar on mobile when switching tabs
    });
  });
  
  // Search
  document.getElementById('searchInput').addEventListener('input', debounce(handleSearch, 300));
  document.getElementById('searchInput').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      handleSearch();
    }
  });
  
  // Add memory button
  document.getElementById('addMemoryBtn').addEventListener('click', () => openMemoryModal());
  
  // Modal close buttons
  document.querySelectorAll('.modal-close').forEach(btn => {
    btn.addEventListener('click', closeAllModals);
  });
  
  // Modal overlay clicks
  document.querySelectorAll('.modal-overlay').forEach(overlay => {
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) closeAllModals();
    });
  });
  
  // Memory form
  document.getElementById('memoryForm').addEventListener('submit', handleMemorySubmit);
  
  // Intel file form
  document.getElementById('intelForm').addEventListener('submit', handleIntelSubmit);
  
  // Refresh buttons
  document.getElementById('refreshBtn').addEventListener('click', loadData);
  
  // Ingest intel button
  document.getElementById('ingestIntelBtn')?.addEventListener('click', handleIngestIntel);
  
  // Add intel file button
  document.getElementById('addIntelBtn')?.addEventListener('click', () => openIntelModal());
  
  // Upload intel button
  document.getElementById('uploadIntelBtn')?.addEventListener('click', () => {
    document.getElementById('intelFileInput').click();
  });
  
  // File input change handler
  document.getElementById('intelFileInput')?.addEventListener('change', handleIntelFileUpload);
}

// =========================================================================
// Data Loading
// =========================================================================

async function loadData() {
  showLoading();
  
  try {
    if (currentTab === 'memories') {
      await loadMemories();
      await loadCategories();
    } else if (currentTab === 'conversations') {
      await loadConversations();
    } else if (currentTab === 'intel') {
      await loadIntelFiles();
    } else if (currentTab === 'stats') {
      await loadStats();
    }
  } catch (error) {
    showToast(`Error loading data: ${error.message}`, 'error');
  }
  
  hideLoading();
}

async function loadMemories() {
  try {
    const options = { limit: 200 };
    if (currentCategory) {
      options.category = currentCategory;
    }
    
    const result = searchQuery 
      ? await api.searchMemories(searchQuery)
      : await api.listMemories(options);
    
    memories = result.memories || [];
    renderMemories();
  } catch (error) {
    console.error('Error loading memories:', error);
    memories = [];
    renderMemories();
  }
}

async function loadCategories() {
  try {
    const result = await api.getCategories();
    categories = result.categories || [];
    renderCategories();
  } catch (error) {
    console.error('Error loading categories:', error);
  }
}

async function loadConversations() {
  try {
    const result = searchQuery
      ? await api.searchConversations(searchQuery)
      : await api.listConversations({ limit: 100 });
    
    conversations = result.conversations || [];
    renderConversations();
  } catch (error) {
    console.error('Error loading conversations:', error);
    conversations = [];
    renderConversations();
  }
}

async function loadIntelFiles() {
  try {
    const result = await api.listIntelFiles();
    intelFiles = result.files || [];
    renderIntelFiles();
  } catch (error) {
    console.error('Error loading intel files:', error);
    intelFiles = [];
    renderIntelFiles();
  }
}

async function loadStats() {
  try {
    const result = await api.getStats();
    renderStats(result);
  } catch (error) {
    console.error('Error loading stats:', error);
  }
}

// =========================================================================
// Rendering
// =========================================================================

function renderMemories() {
  const container = document.getElementById('memoryList');
  
  if (memories.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <div class="empty-state-icon">🧠</div>
        <div class="empty-state-title">${searchQuery ? 'No results found' : 'No memories yet'}</div>
        <div class="empty-state-desc">${searchQuery ? 'Try a different search term' : 'Add your first memory to get started'}</div>
        ${!searchQuery ? '<button class="btn btn-primary" onclick="openMemoryModal()">+ Add Memory</button>' : ''}
      </div>
    `;
    return;
  }
  
  container.innerHTML = `
    <div class="memory-grid">
      ${memories.map(memory => renderMemoryCard(memory)).join('')}
    </div>
  `;
}

function renderMemoryCard(memory) {
  const importanceClass = memory.importance >= 8 ? 'importance-high' 
    : memory.importance >= 5 ? 'importance-medium' 
    : 'importance-low';
  
  const updatedDate = memory.updated_at 
    ? new Date(memory.updated_at).toLocaleDateString()
    : 'Unknown';
  
  // Calculate value size and health indicators
  const valueLength = (memory.value || '').length;
  const sizeIndicator = getSizeIndicator(valueLength);
  const healthStatus = getMemoryHealth(memory);
  
  return `
    <div class="memory-card" onclick="viewMemory(${memory.id})">
      <div class="memory-card-header">
        <div class="memory-key">${escapeHtml(memory.key)}</div>
        <span class="memory-category">${escapeHtml(memory.category)}</span>
      </div>
      <div class="memory-value">${escapeHtml(memory.value)}</div>
      <div class="memory-card-footer">
        <div class="memory-meta">
          <span title="Importance"><span class="importance-badge ${importanceClass}">${memory.importance}</span></span>
          <span title="Size: ${valueLength} chars">${sizeIndicator}</span>
          <span title="Updated">${updatedDate}</span>
          ${memory.has_embedding ? '<span title="Has embedding - semantic search enabled">🔮</span>' : '<span title="No embedding - keyword search only">⚪</span>'}
          ${healthStatus.icon ? `<span title="${healthStatus.message}">${healthStatus.icon}</span>` : ''}
        </div>
        <div class="memory-actions">
          ${!memory.has_embedding ? `<button class="btn btn-icon" onclick="event.stopPropagation(); reembedMemory(${memory.id})" title="Generate embedding">🔮</button>` : ''}
          <button class="btn btn-icon" onclick="event.stopPropagation(); editMemory(${memory.id})" title="Edit">✏️</button>
          <button class="btn btn-icon" onclick="event.stopPropagation(); confirmDeleteMemory(${memory.id})" title="Delete">🗑️</button>
        </div>
      </div>
    </div>
  `;
}

function getSizeIndicator(length) {
  if (length < 100) return '📏S';
  if (length < 500) return '📏M';
  if (length < 1000) return '📏L';
  return '📏XL';
}

function getMemoryHealth(memory) {
  const issues = [];
  
  // Check for potential issues
  if (!memory.value || memory.value.trim().length < 5) {
    issues.push('Value too short');
  }
  if (!memory.key || memory.key.trim().length < 2) {
    issues.push('Key too short');
  }
  if (memory.value && memory.value.length > 5000) {
    issues.push('Value very long - may affect performance');
  }
  if (!memory.has_embedding) {
    // Not really an issue, just informational
  }
  
  if (issues.length === 0) {
    return { icon: '', message: '' };
  } else if (issues.length === 1 && issues[0].includes('long')) {
    return { icon: '⚠️', message: issues.join(', ') };
  } else if (issues.length > 0) {
    return { icon: '⚠️', message: issues.join(', ') };
  }
  return { icon: '', message: '' };
}

function renderCategories() {
  const container = document.getElementById('categoryList');
  
  const allCount = memories.length || categories.reduce((sum, c) => sum + c.count, 0);
  
  container.innerHTML = `
    <div class="category-list">
      <div class="category-item ${!currentCategory ? 'active' : ''}" onclick="filterByCategory(null)">
        <span class="category-name">All</span>
        <span class="category-count">${allCount}</span>
      </div>
      ${categories.map(cat => `
        <div class="category-item ${currentCategory === cat.name ? 'active' : ''}" onclick="filterByCategory('${escapeHtml(cat.name)}')">
          <span class="category-name">${escapeHtml(cat.name)}</span>
          <span class="category-count">${cat.count}</span>
        </div>
      `).join('')}
    </div>
  `;
}

function renderConversations() {
  const container = document.getElementById('conversationList');
  
  if (conversations.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <div class="empty-state-icon">💬</div>
        <div class="empty-state-title">No conversations yet</div>
        <div class="empty-state-desc">Conversations with Jarvis will appear here</div>
      </div>
    `;
    return;
  }
  
  container.innerHTML = `
    <div class="conversation-list">
      ${conversations.map((conv, index) => `
        <div class="conversation-item" onclick="viewConversation(${index})" style="cursor: pointer;">
          <div class="conversation-query">👤 ${escapeHtml(conv.user_query || '')}</div>
          <div class="conversation-response">🤖 ${escapeHtml(truncate(conv.jarvis_response || '', 200))}</div>
          <div class="conversation-meta">
            <span>${formatDate(conv.timestamp)}</span>
            ${conv.tools_used && conv.tools_used.length ? `<span>🔧 ${Array.isArray(conv.tools_used) ? conv.tools_used.join(', ') : conv.tools_used}</span>` : ''}
            <span>${conv.success ? '✅' : '❌'}</span>
          </div>
        </div>
      `).join('')}
    </div>
  `;
}

function renderIntelFiles() {
  const container = document.getElementById('intelList');
  
  if (intelFiles.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <div class="empty-state-icon">📁</div>
        <div class="empty-state-title">No intel files</div>
        <div class="empty-state-desc">Add .md or .txt files to jarvis-intel/ folder</div>
        <button class="btn btn-primary" onclick="openIntelModal()">+ Create File</button>
      </div>
    `;
    return;
  }
  
  container.innerHTML = `
    <div class="file-list">
      ${intelFiles.map(file => `
        <div class="file-item" onclick="viewIntelFile('${escapeHtml(file.name)}')">
          <div class="file-info">
            <span class="file-icon">${file.extension === '.md' ? '📝' : '📄'}</span>
            <div>
              <div class="file-name">${escapeHtml(file.name)}</div>
              <div class="file-meta">${formatFileSize(file.size)} • ${formatDate(file.modified * 1000)}</div>
            </div>
          </div>
          <div class="file-actions">
            <button class="btn btn-icon" onclick="event.stopPropagation(); editIntelFile('${escapeHtml(file.name)}')" title="Edit">✏️</button>
            <button class="btn btn-icon" onclick="event.stopPropagation(); confirmDeleteFile('${escapeHtml(file.name)}')" title="Delete">🗑️</button>
          </div>
        </div>
      `).join('')}
    </div>
  `;
}

function renderStats(data) {
  const container = document.getElementById('statsPanel');
  
  const memory = data.memory || {};
  const convStats = data.conversations || {};
  
  container.innerHTML = `
    <div class="memory-list" style="min-height: 0;">
    <div class="stats-grid">
      <div class="stat-card">
        <div class="stat-value">${memory.total_memories || 0}</div>
        <div class="stat-label">Total Memories</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">${memory.with_embeddings || 0}</div>
        <div class="stat-label">With Embeddings</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">${(memory.categories || []).length}</div>
        <div class="stat-label">Categories</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">${memory.recent_7_days || 0}</div>
        <div class="stat-label">Updated (7 days)</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">${convStats.total_conversations || 0}</div>
        <div class="stat-label">Conversations</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">${convStats.success_rate || 0}%</div>
        <div class="stat-label">Success Rate</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">${memory.db_size_mb || 0} MB</div>
        <div class="stat-label">Database Size</div>
      </div>
    </div>
    
    <div style="padding: var(--space-lg);">
      <h3 style="margin-bottom: var(--space-md);">Categories</h3>
      <div class="category-list">
        ${(memory.categories || []).map(cat => `
          <div class="category-item" onclick="switchTab('memories'); filterByCategory('${escapeHtml(cat.name)}')">
            <span class="category-name">${escapeHtml(cat.name)}</span>
            <span class="category-count">${cat.count}</span>
          </div>
        `).join('')}
      </div>
    </div>
    
    ${(convStats.top_tools || []).length > 0 ? `
    <div style="padding: var(--space-lg);">
      <h3 style="margin-bottom: var(--space-md);">Top Tools Used</h3>
      <div class="category-list">
        ${(convStats.top_tools || []).map(tool => `
          <div class="category-item">
            <span class="category-name">${escapeHtml(tool.name)}</span>
            <span class="category-count">${tool.count}</span>
          </div>
        `).join('')}
      </div>
    </div>
    ` : ''}
    </div>
  `;
}

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

// =========================================================================
// Tab Navigation
// =========================================================================

function switchTab(tab) {
  currentTab = tab;
  searchQuery = '';
  document.getElementById('searchInput').value = '';
  document.getElementById('searchInput').placeholder = SEARCH_PLACEHOLDERS[tab] || 'Search...';
  
  // Update nav tabs (both desktop and mobile)
  document.querySelectorAll('.nav-tab').forEach(t => {
    t.classList.toggle('active', t.dataset.tab === tab);
  });
  
  // Close sidebar on mobile after tab switch
  closeSidebar();
  
  // Update panels
  document.querySelectorAll('.tab-panel').forEach(p => {
    p.classList.toggle('active', p.id === `${tab}Panel`);
  });
  
  // Show/hide sidebar for memories tab
  document.querySelector('.sidebar').style.display = tab === 'memories' ? 'flex' : 'none';
  
  // Update toolbar buttons
  document.getElementById('addMemoryBtn').style.display = tab === 'memories' ? 'flex' : 'none';
  document.getElementById('addIntelBtn').style.display = tab === 'intel' ? 'flex' : 'none';
  document.getElementById('uploadIntelBtn').style.display = tab === 'intel' ? 'flex' : 'none';
  document.getElementById('ingestIntelBtn').style.display = tab === 'intel' ? 'flex' : 'none';
  
  // Load data for tab
  loadData();
}

// =========================================================================
// Category Filter
// =========================================================================

function filterByCategory(category) {
  currentCategory = category;
  loadMemories();
  renderCategories();
  closeSidebar(); // Close sidebar on mobile after selecting category
}

// =========================================================================
// Search
// =========================================================================

function handleSearch() {
  searchQuery = document.getElementById('searchInput').value.trim();
  loadData();
}

// =========================================================================
// Memory CRUD
// =========================================================================

function openMemoryModal(memory = null) {
  editingMemory = memory;
  
  const modal = document.getElementById('memoryModal');
  const title = document.getElementById('memoryModalTitle');
  const form = document.getElementById('memoryForm');
  
  title.textContent = memory ? 'Edit Memory' : 'Add Memory';
  
  // Populate form
  document.getElementById('memoryCategory').value = memory?.category || '';
  document.getElementById('memoryKey').value = memory?.key || '';
  document.getElementById('memoryValue').value = memory?.value || '';
  document.getElementById('memoryImportance').value = memory?.importance || 5;
  
  modal.classList.add('active');
}

async function handleMemorySubmit(e) {
  e.preventDefault();
  
  const data = {
    category: document.getElementById('memoryCategory').value.trim(),
    key: document.getElementById('memoryKey').value.trim(),
    value: document.getElementById('memoryValue').value.trim(),
    importance: parseInt(document.getElementById('memoryImportance').value, 10)
  };
  
  try {
    let memoryId;
    let isNew = !editingMemory;
    
    if (editingMemory) {
      await api.updateMemory(editingMemory.id, data);
      memoryId = editingMemory.id;
      showToast('Memory updated!', 'success');
    } else {
      const result = await api.createMemory(data);
      memoryId = result.id;
      showToast('Memory created!', 'success');
    }
    
    closeAllModals();
    await loadMemories();
    await loadCategories();
    
    // Ask if user wants to generate/regenerate embedding
    const action = isNew ? 'generate' : 'regenerate';
    if (confirm(`Would you like to ${action} the embedding now?\n\nThis enables semantic search (finding by meaning, not just keywords).`)) {
      await reembedMemory(memoryId);
    }
  } catch (error) {
    showToast(`Error: ${error.message}`, 'error');
  }
}

async function viewMemory(id) {
  try {
    const result = await api.getMemory(id);
    const memory = result.memory;
    
    // Show in view modal
    const modal = document.getElementById('viewModal');
    const content = document.getElementById('viewContent');
    
    const valueLength = (memory.value || '').length;
    
    content.innerHTML = `
      <div class="form-group">
        <label class="form-label">Category</label>
        <div class="code-block">${escapeHtml(memory.category)}</div>
      </div>
      <div class="form-group">
        <label class="form-label">Key</label>
        <div class="code-block">${escapeHtml(memory.key)}</div>
      </div>
      <div class="form-group">
        <label class="form-label">Value</label>
        <div class="code-block" style="max-height: 300px; overflow-y: auto;">${escapeHtml(memory.value)}</div>
      </div>
      <div class="form-group">
        <label class="form-label">Details</label>
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: var(--space-sm);">
          <div><strong>Importance:</strong> ${memory.importance}/10</div>
          <div><strong>Size:</strong> ${valueLength} chars</div>
          <div><strong>Embedding:</strong> ${memory.has_embedding ? '✅ Yes' : '❌ No'}</div>
          <div><strong>Source:</strong> ${escapeHtml(memory.source || 'Unknown')}</div>
        </div>
      </div>
      <div class="form-group">
        <label class="form-label">Timestamps</label>
        <div><strong>Created:</strong> ${formatDate(memory.created_at)}</div>
        <div><strong>Updated:</strong> ${formatDate(memory.updated_at)}</div>
      </div>
      ${memory.metadata ? `
      <div class="form-group">
        <label class="form-label">Metadata</label>
        <div class="code-block">${JSON.stringify(memory.metadata, null, 2)}</div>
      </div>
      ` : ''}
      ${!memory.has_embedding ? `
      <div class="form-group" style="background: var(--warning-bg); padding: var(--space-md); border-radius: var(--radius-md); border-left: 3px solid var(--warning);">
        <strong>⚠️ No Embedding</strong><br>
        This memory won't appear in semantic search. Click "🔮 Re-embed" to generate an embedding.
      </div>
      ` : ''}
      <div class="form-group" style="margin-top: var(--space-lg); display: flex; flex-wrap: wrap; gap: var(--space-sm);">
        <button class="btn btn-primary" onclick="editMemory(${memory.id}); closeAllModals();">✏️ Edit</button>
        <button class="btn btn-secondary" onclick="reembedMemory(${memory.id});" title="Re-generate embedding for semantic search">🔮 Re-embed</button>
        <button class="btn btn-danger" onclick="confirmDeleteMemory(${memory.id}); closeAllModals();">🗑️ Delete</button>
      </div>
    `;
    
    modal.classList.add('active');
  } catch (error) {
    showToast(`Error: ${error.message}`, 'error');
  }
}

async function editMemory(id) {
  try {
    const result = await api.getMemory(id);
    openMemoryModal(result.memory);
  } catch (error) {
    showToast(`Error: ${error.message}`, 'error');
  }
}

async function confirmDeleteMemory(id) {
  if (confirm('Are you sure you want to delete this memory?')) {
    try {
      await api.deleteMemory(id);
      showToast('Memory deleted', 'success');
      await loadMemories();
      await loadCategories();
    } catch (error) {
      showToast(`Error: ${error.message}`, 'error');
    }
  }
}

async function reembedMemory(id) {
  try {
    showToast('Generating embedding...', 'info');
    const result = await api.reembedMemory(id);
    showToast(result.message || 'Embedding generated successfully!', 'success');
    
    // Refresh the memory view
    await viewMemory(id);
    await loadMemories();
  } catch (error) {
    showToast(`Re-embed failed: ${error.message}`, 'error');
  }
}

// =========================================================================
// Intel File CRUD
// =========================================================================

function openIntelModal(file = null) {
  editingFile = file;
  
  const modal = document.getElementById('intelModal');
  const title = document.getElementById('intelModalTitle');
  
  title.textContent = file ? 'Edit Intel File' : 'Create Intel File';
  
  document.getElementById('intelFilename').value = file?.name || '';
  document.getElementById('intelFilename').disabled = !!file;
  document.getElementById('intelContent').value = file?.content || '';
  
  modal.classList.add('active');
}

async function handleIntelSubmit(e) {
  e.preventDefault();
  
  const filename = document.getElementById('intelFilename').value.trim();
  const content = document.getElementById('intelContent').value;
  
  // Validate content
  const validation = validateIntelContent(content, filename);
  if (!validation.ok) {
    showToast(`Validation warning: ${validation.message}`, 'warning');
    // Continue anyway, just warn
  }
  
  try {
    if (editingFile) {
      await api.updateIntelFile(editingFile.name, content);
      showToast('File saved successfully', 'success');
    } else {
      await api.createIntelFile(filename, content);
      showToast('File created successfully', 'success');
    }
    
    closeAllModals();
    await loadIntelFiles();
  } catch (error) {
    showToast(`Error: ${error.message}`, 'error');
  }
}

function validateIntelContent(content, filename) {
  const issues = [];
  
  // Check for images (markdown image syntax)
  if (/!\[.*?\]\(.*?\)/.test(content)) {
    issues.push('Images detected - they cannot be processed');
  }
  
  // Check for base64 data
  if (/data:image/.test(content)) {
    issues.push('Base64 image data detected');
  }
  
  // Check for very short content
  if (content.trim().length < 10) {
    issues.push('Content too short');
  }
  
  // Check for binary/non-text characters
  if (/[\x00-\x08\x0B\x0C\x0E-\x1F]/.test(content)) {
    issues.push('Binary characters detected');
  }
  
  if (issues.length > 0) {
    return { ok: false, message: issues.join('; ') };
  }
  return { ok: true, message: '' };
}

async function handleIntelFileUpload(e) {
  const files = e.target.files;
  if (!files || files.length === 0) return;
  
  let successCount = 0;
  let errorCount = 0;
  
  for (const file of files) {
    // Validate file type
    if (!file.name.endsWith('.md') && !file.name.endsWith('.txt')) {
      showToast(`Skipped ${file.name}: Only .md and .txt files allowed`, 'warning');
      errorCount++;
      continue;
    }
    
    // Validate file size (max 1MB)
    if (file.size > 1024 * 1024) {
      showToast(`Skipped ${file.name}: File too large (max 1MB)`, 'warning');
      errorCount++;
      continue;
    }
    
    try {
      const content = await file.text();
      
      // Validate content
      const validation = validateIntelContent(content, file.name);
      if (!validation.ok) {
        showToast(`Warning for ${file.name}: ${validation.message}`, 'warning');
      }
      
      // Try to create the file
      try {
        await api.createIntelFile(file.name, content);
        successCount++;
      } catch (error) {
        // File might already exist, try updating
        if (error.message.includes('already exists')) {
          if (confirm(`${file.name} already exists. Overwrite?`)) {
            await api.updateIntelFile(file.name, content);
            successCount++;
          }
        } else {
          throw error;
        }
      }
    } catch (error) {
      showToast(`Error uploading ${file.name}: ${error.message}`, 'error');
      errorCount++;
    }
  }
  
  // Reset input
  e.target.value = '';
  
  // Show summary
  if (successCount > 0) {
    showToast(`Uploaded ${successCount} file(s)${errorCount > 0 ? `, ${errorCount} failed` : ''}`, 'success');
    await loadIntelFiles();
  } else if (errorCount > 0) {
    showToast(`All ${errorCount} uploads failed`, 'error');
  }
}

async function viewIntelFile(filename) {
  try {
    const result = await api.getIntelFile(filename);
    const file = result.file;
    
    const modal = document.getElementById('viewModal');
    const content = document.getElementById('viewContent');
    
    // Check for potential issues
    const validation = validateIntelContent(file.content, file.name);
    
    content.innerHTML = `
      <div class="form-group">
        <label class="form-label">Filename</label>
        <div class="code-block">${escapeHtml(file.name)}</div>
      </div>
      ${!validation.ok ? `
      <div class="form-group" style="background: var(--warning-bg); padding: var(--space-md); border-radius: var(--radius-md); border-left: 3px solid var(--warning);">
        <strong>⚠️ Content Issues:</strong> ${escapeHtml(validation.message)}
      </div>
      ` : ''}
      <div class="form-group">
        <label class="form-label">Content</label>
        <div class="code-block" style="max-height: 400px; overflow-y: auto; white-space: pre-wrap;">${escapeHtml(file.content)}</div>
      </div>
      <div class="form-group">
        <label class="form-label">Size</label>
        <div>${formatFileSize(file.size)}</div>
      </div>
      <div class="form-group" style="margin-top: var(--space-lg); display: flex; gap: var(--space-sm);">
        <button class="btn btn-primary" onclick="editIntelFile('${escapeHtml(file.name)}'); closeAllModals();">Edit File</button>
        <button class="btn btn-danger" onclick="confirmDeleteFile('${escapeHtml(file.name)}'); closeAllModals();">Delete</button>
      </div>
    `;
    
    modal.classList.add('active');
  } catch (error) {
    showToast(`Error: ${error.message}`, 'error');
  }
}

async function editIntelFile(filename) {
  try {
    const result = await api.getIntelFile(filename);
    openIntelModal(result.file);
  } catch (error) {
    showToast(`Error: ${error.message}`, 'error');
  }
}

async function confirmDeleteFile(filename) {
  if (confirm(`Are you sure you want to delete ${filename}?`)) {
    try {
      await api.deleteIntelFile(filename);
      showToast('File deleted', 'success');
      await loadIntelFiles();
    } catch (error) {
      showToast(`Error: ${error.message}`, 'error');
    }
  }
}

async function handleIngestIntel() {
  try {
    showToast('Ingesting intel files... (unchanged files will be skipped)', 'info');
    const result = await api.ingestIntel();
    showToast(result.speech || 'Intel ingested successfully', 'success');
  } catch (error) {
    showToast(`Error: ${error.message}`, 'error');
  }
}

// =========================================================================
// Conversation View
// =========================================================================

function viewConversation(index) {
  const conv = conversations[index];
  if (!conv) return;
  
  const modal = document.getElementById('viewModal');
  const content = document.getElementById('viewContent');
  
  const toolsUsed = conv.tools_used 
    ? (Array.isArray(conv.tools_used) ? conv.tools_used : [conv.tools_used])
    : [];
  
  content.innerHTML = `
    <div class="form-group">
      <label class="form-label">📅 Timestamp</label>
      <div>${formatDate(conv.timestamp)}</div>
    </div>
    <div class="form-group">
      <label class="form-label">🆔 Session</label>
      <div class="code-block" style="font-size: 0.8em;">${escapeHtml(conv.session_id || 'N/A')}</div>
    </div>
    <div class="form-group">
      <label class="form-label">👤 User Query</label>
      <div class="code-block" style="background: var(--info-bg); border-left: 3px solid var(--info);">${escapeHtml(conv.user_query || '')}</div>
    </div>
    <div class="form-group">
      <label class="form-label">🤖 Jarvis Response</label>
      <div class="code-block" style="max-height: 400px; overflow-y: auto; white-space: pre-wrap;">${escapeHtml(conv.jarvis_response || '')}</div>
    </div>
    ${toolsUsed.length > 0 ? `
    <div class="form-group">
      <label class="form-label">🔧 Tools Used</label>
      <div style="display: flex; flex-wrap: wrap; gap: var(--space-xs);">
        ${toolsUsed.map(tool => `<span class="memory-category">${escapeHtml(tool)}</span>`).join('')}
      </div>
    </div>
    ` : ''}
    <div class="form-group">
      <label class="form-label">Status</label>
      <div>${conv.success ? '✅ Success' : '❌ Failed'}</div>
    </div>
    ${conv.metadata ? `
    <div class="form-group">
      <label class="form-label">Metadata</label>
      <div class="code-block" style="font-size: 0.85em;">${JSON.stringify(typeof conv.metadata === 'string' ? JSON.parse(conv.metadata) : conv.metadata, null, 2)}</div>
    </div>
    ` : ''}
  `;
  
  modal.classList.add('active');
}

// =========================================================================
// Modal Helpers
// =========================================================================

function closeAllModals() {
  document.querySelectorAll('.modal-overlay').forEach(m => m.classList.remove('active'));
  editingMemory = null;
  editingFile = null;
}

// =========================================================================
// Toast Notifications
// =========================================================================

function showToast(message, type = 'info') {
  const container = document.getElementById('toastContainer');
  
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.textContent = message;
  
  container.appendChild(toast);
  
  setTimeout(() => {
    toast.style.opacity = '0';
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

// =========================================================================
// Loading State
// =========================================================================

function showLoading() {
  // Optional: show loading indicator
}

function hideLoading() {
  // Optional: hide loading indicator
}

// =========================================================================
// Utility Functions
// =========================================================================

function escapeHtml(text) {
  if (!text) return '';
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

function truncate(text, length) {
  if (!text) return '';
  return text.length > length ? text.substring(0, length) + '...' : text;
}

function formatDate(dateStr) {
  if (!dateStr) return 'Unknown';
  try {
    const date = new Date(dateStr);
    return date.toLocaleString();
  } catch {
    return dateStr;
  }
}

function formatFileSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function debounce(fn, delay) {
  let timeout;
  return (...args) => {
    clearTimeout(timeout);
    timeout = setTimeout(() => fn(...args), delay);
  };
}
