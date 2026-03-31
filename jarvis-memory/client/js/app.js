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
let scheduledTasks = [];
let searchQuery = '';
let editingMemory = null;
let editingFile = null;
let editingScheduledTask = null;
const DEFAULT_TIMEZONE = Intl.DateTimeFormat().resolvedOptions().timeZone || 'America/Los_Angeles';
let scheduledStatusFilter = 'all';
let scheduledSortBy = 'next_run_asc';
let scheduledTaskRuns = {};
let scheduledTaskRunsLoading = {};
let scheduledTaskRunsExpanded = {};

// Search placeholders per tab
const SEARCH_PLACEHOLDERS = {
  memories: 'Search memories (FTS5)...',
  intel: 'Search intel files...',
  conversations: 'Search conversations...',
  scheduled: 'Search scheduled tasks...',
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
  document.getElementById('addScheduledTaskBtn')?.addEventListener('click', () => openScheduledTaskModal());
  
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
  document.getElementById('scheduledTaskForm').addEventListener('submit', handleScheduledTaskSubmit);
  document.getElementById('scheduledTaskType')?.addEventListener('change', handleScheduledTaskTypeChange);
  document.getElementById('scheduledStatusFilter')?.addEventListener('change', (e) => {
    scheduledStatusFilter = e.target.value;
    renderScheduledTasks();
  });
  document.getElementById('scheduledSortBy')?.addEventListener('change', (e) => {
    scheduledSortBy = e.target.value;
    renderScheduledTasks();
  });
  
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
    } else if (currentTab === 'scheduled') {
      await loadScheduledTasks();
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

async function loadScheduledTasks() {
  try {
    const result = await api.listScheduledTasks({ status: 'all', limit: 200 });
    scheduledTasks = result.tasks || [];
    renderScheduledTasks();
  } catch (error) {
    console.error('Error loading scheduled tasks:', error);
    scheduledTasks = [];
    renderScheduledTasks();
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

function renderScheduledTasks() {
  const container = document.getElementById('scheduledTaskList');
  const filteredTasks = getVisibleScheduledTasks();

  if (filteredTasks.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <div class="empty-state-icon">⏱️</div>
        <div class="empty-state-title">${searchQuery ? 'No scheduled tasks found' : 'No scheduled tasks yet'}</div>
        <div class="empty-state-desc">${searchQuery || scheduledStatusFilter !== 'all' ? 'Try a different search term or filter' : 'Create a scheduled query or workflow to run later'}</div>
        ${!searchQuery ? '<button class="btn btn-primary" onclick="openScheduledTaskModal()">+ Add Task</button>' : ''}
      </div>
    `;
    return;
  }

  container.innerHTML = `
    <div class="memory-grid">
      ${filteredTasks.map(task => renderScheduledTaskCard(task)).join('')}
    </div>
  `;
}

function renderScheduledTaskCard(task) {
  const payload = parseJsonSafe(task.task_payload) || {};
  const scheduleExpr = parseJsonSafe(task.schedule_expr) || {};
  const enabledBadge = task.enabled ? 'enabled' : 'disabled';
  const status = task.last_status || (task.enabled ? 'scheduled' : 'idle');
  const statusClass = getRunStatusClass(status);
  const dueClass = getScheduledDueClass(task.next_run_at);
  const relativeNextRun = formatScheduledRelativeTime(task.next_run_at);
  const lastPreview = getScheduledLastPreview(task);
  const targetText = task.task_type === 'workflow'
    ? (task.task_target || payload.workflow_id || 'workflow')
    : (payload.query || '').trim();
  const isExpanded = !!scheduledTaskRunsExpanded[task.id];
  const isLoading = !!scheduledTaskRunsLoading[task.id];
  const runs = scheduledTaskRuns[task.id] || [];

  return `
    <div class="memory-card scheduled-task-card ${dueClass}" onclick="viewScheduledTask(${task.id})">
      <div class="memory-card-header">
        <div>
          <div class="memory-key">${escapeHtml(task.name)}</div>
          <div class="scheduled-task-subtitle">${escapeHtml(task.task_type)} • ${escapeHtml(payload.schedule_summary || task.schedule_type)}</div>
        </div>
        <div class="scheduled-task-badges">
          <span class="memory-category">${escapeHtml(task.mode)}</span>
          <span class="status-badge ${enabledBadge}">${task.enabled ? 'Enabled' : 'Disabled'}</span>
          <span class="status-badge run-status ${statusClass}">${escapeHtml(formatRunStatus(status))}</span>
        </div>
      </div>
      <div class="memory-value">${escapeHtml(truncate(targetText || JSON.stringify(scheduleExpr), 180))}</div>
      <div class="scheduled-next-run">
        <span class="scheduled-next-run-label">Next run</span>
        <span class="scheduled-next-run-value">${escapeHtml(formatScheduledNextRun(task.next_run_at))}</span>
        ${relativeNextRun ? `<span class="scheduled-next-run-relative">${escapeHtml(relativeNextRun)}</span>` : ''}
      </div>
      ${lastPreview ? `
        <div class="scheduled-last-preview ${lastPreview.kind}">
          <div class="scheduled-last-preview-label">${escapeHtml(lastPreview.label)}</div>
          <div class="scheduled-last-preview-text">${escapeHtml(truncate(lastPreview.text, 220))}</div>
        </div>
      ` : ''}
      <div class="memory-card-footer">
        <div class="memory-meta">
          <span title="Last status">📌 ${escapeHtml(status)}</span>
          ${task.last_run_at ? `<span title="Last run">🕘 ${escapeHtml(formatDate(task.last_run_at))}</span>` : ''}
          ${task.last_duration_ms ? `<span title="Last duration">⏱️ ${Math.round(task.last_duration_ms)}ms</span>` : ''}
        </div>
        <div class="memory-actions">
          <button class="btn btn-icon" onclick="event.stopPropagation(); toggleScheduledTaskRuns(${task.id})" title="Toggle recent runs">${isExpanded ? '▾' : '▸'}</button>
          <button class="btn btn-icon" onclick="event.stopPropagation(); runScheduledTaskNow(${task.id})" title="Run now">▶️</button>
          <button class="btn btn-icon" onclick="event.stopPropagation(); editScheduledTask(${task.id})" title="Edit">✏️</button>
          <button class="btn btn-icon" onclick="event.stopPropagation(); cancelScheduledTask(${task.id})" title="Cancel">⏸️</button>
          <button class="btn btn-icon" onclick="event.stopPropagation(); confirmDeleteScheduledTask(${task.id})" title="Delete">🗑️</button>
        </div>
      </div>
      ${isExpanded ? `
        <div class="scheduled-inline-runs" onclick="event.stopPropagation()">
          <div class="scheduled-inline-runs-title">Recent Runs</div>
          ${isLoading ? `
            <div class="empty-inline">Loading run history...</div>
          ` : runs.length === 0 ? `
            <div class="empty-inline">No run history yet.</div>
          ` : `
            <div class="run-history-list">
              ${runs.map(run => `
                <div class="run-history-item">
                  <div class="run-history-head">
                    <span class="status-badge run-status ${getRunStatusClass(run.status)}">${escapeHtml(formatRunStatus(run.status))}</span>
                    <span>${escapeHtml(formatDate(run.started_at))}</span>
                  </div>
                  <div class="run-history-body">
                    ${run.speech ? `<div>${escapeHtml(truncate(run.speech, 200))}</div>` : ''}
                    ${run.error ? `<div class="run-history-error">${escapeHtml(run.error)}</div>` : ''}
                    ${run.tools_used ? `<div class="run-history-meta">Tools: ${escapeHtml(run.tools_used)}</div>` : ''}
                  </div>
                </div>
              `).join('')}
            </div>
          `}
        </div>
      ` : ''}
    </div>
  `;
}

function getVisibleScheduledTasks() {
  let tasks = [...scheduledTasks];

  if (searchQuery) {
    tasks = tasks.filter(task => scheduledTaskMatchesQuery(task, searchQuery));
  }

  tasks = tasks.filter(task => matchesScheduledStatusFilter(task, scheduledStatusFilter));

  tasks.sort((a, b) => compareScheduledTasks(a, b, scheduledSortBy));
  return tasks;
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
  document.getElementById('addScheduledTaskBtn').style.display = tab === 'scheduled' ? 'flex' : 'none';
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

function matchesScheduledStatusFilter(task, filter) {
  const status = (task.last_status || '').toLowerCase();
  if (filter === 'all') return true;
  if (filter === 'enabled') return !!task.enabled;
  if (filter === 'disabled') return !task.enabled;
  if (filter === 'never_run') return !task.last_run_at;
  return status === filter;
}

function compareScheduledTasks(a, b, sortBy) {
  const bNext = b.next_run_at ? getScheduledNextRunTimestamp(b.next_run_at) : Number.MAX_SAFE_INTEGER;
  const aNextTs = a.next_run_at ? getScheduledNextRunTimestamp(a.next_run_at) : Number.MAX_SAFE_INTEGER;
  const aUpdated = a.updated_at ? new Date(a.updated_at).getTime() : 0;
  const bUpdated = b.updated_at ? new Date(b.updated_at).getTime() : 0;

  switch (sortBy) {
    case 'next_run_desc':
      return bNext - aNextTs;
    case 'updated_desc':
      return bUpdated - aUpdated;
    case 'name_asc':
      return String(a.name || '').localeCompare(String(b.name || ''));
    case 'status_asc':
      return formatRunStatus(a.last_status || (a.enabled ? 'scheduled' : 'idle'))
        .localeCompare(formatRunStatus(b.last_status || (b.enabled ? 'scheduled' : 'idle')));
    case 'next_run_asc':
    default:
      return aNextTs - bNext;
  }
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

function openScheduledTaskModal(task = null) {
  editingScheduledTask = task;

  const modal = document.getElementById('scheduledTaskModal');
  const title = document.getElementById('scheduledTaskModalTitle');
  const payload = parseJsonSafe(task?.task_payload) || {};

  title.textContent = task ? 'Edit Scheduled Task' : 'Add Scheduled Task';

  document.getElementById('scheduledTaskName').value = task?.name || '';
  document.getElementById('scheduledTaskType').value = task?.task_type || 'query';
  document.getElementById('scheduledTaskQuery').value = payload.query || '';
  document.getElementById('scheduledTaskWorkflowId').value = task?.task_target || payload.workflow_id || '';
  document.getElementById('scheduledTaskWhen').value = payload.when_original || '';
  document.getElementById('scheduledTaskTimezone').value = task?.timezone || DEFAULT_TIMEZONE;
  document.getElementById('scheduledTaskExecutionMode').value = task?.mode || api.mode || 'cloud';
  document.getElementById('scheduledTaskMaxRetries').value = task?.max_retries ?? 1;
  document.getElementById('scheduledTaskTimeout').value = task?.timeout_seconds ?? 300;
  document.getElementById('scheduledTaskEnabled').checked = task?.enabled ?? true;
  document.getElementById('scheduledTaskAllowOverlap').checked = !!task?.allow_overlap;

  handleScheduledTaskTypeChange();
  modal.classList.add('active');
}

function handleScheduledTaskTypeChange() {
  const type = document.getElementById('scheduledTaskType').value;
  document.getElementById('scheduledTaskQueryGroup').style.display = type === 'query' ? 'block' : 'none';
  document.getElementById('scheduledTaskWorkflowGroup').style.display = type === 'workflow' ? 'block' : 'none';
}

async function handleScheduledTaskSubmit(e) {
  e.preventDefault();

  const taskType = document.getElementById('scheduledTaskType').value;
  const data = {
    name: document.getElementById('scheduledTaskName').value.trim(),
    task_type: taskType,
    query: document.getElementById('scheduledTaskQuery').value.trim(),
    workflow_id: document.getElementById('scheduledTaskWorkflowId').value.trim(),
    when: document.getElementById('scheduledTaskWhen').value.trim(),
    timezone: document.getElementById('scheduledTaskTimezone').value.trim() || null,
    execution_mode: document.getElementById('scheduledTaskExecutionMode').value,
    max_retries: parseInt(document.getElementById('scheduledTaskMaxRetries').value, 10) || 1,
    timeout_seconds: parseInt(document.getElementById('scheduledTaskTimeout').value, 10) || 300,
    enabled: document.getElementById('scheduledTaskEnabled').checked,
    allow_overlap: document.getElementById('scheduledTaskAllowOverlap').checked
  };

  if (!data.name || !data.when) {
    showToast('Task name and schedule are required', 'error');
    return;
  }
  if (taskType === 'query' && !data.query) {
    showToast('Query is required for query tasks', 'error');
    return;
  }
  if (taskType === 'workflow' && !data.workflow_id) {
    showToast('Workflow ID is required for workflow tasks', 'error');
    return;
  }

  try {
    if (editingScheduledTask) {
      await api.updateScheduledTask(editingScheduledTask.id, data);
      showToast('Scheduled task updated', 'success');
    } else {
      await api.createScheduledTask(data);
      showToast('Scheduled task created', 'success');
    }
    closeAllModals();
    await loadScheduledTasks();
  } catch (error) {
    showToast(`Error: ${error.message}`, 'error');
  }
}

async function viewScheduledTask(id) {
  try {
    const [taskResult, runsResult] = await Promise.all([
      api.getScheduledTask(id),
      api.listScheduledTaskRuns(id, 10)
    ]);
    const task = taskResult.task;
    const runs = runsResult.runs || [];
    const payload = parseJsonSafe(task.task_payload) || {};
    const scheduleExpr = parseJsonSafe(task.schedule_expr) || {};

    const modal = document.getElementById('viewModal');
    const content = document.getElementById('viewContent');

    content.innerHTML = `
      <div class="form-group">
        <label class="form-label">Task Name</label>
        <div class="code-block">${escapeHtml(task.name)}</div>
      </div>
      <div class="form-group">
        <label class="form-label">Execution</label>
        <div><strong>Type:</strong> ${escapeHtml(task.task_type)}</div>
        <div><strong>Mode:</strong> ${escapeHtml(task.mode)}</div>
        <div><strong>Timezone:</strong> ${escapeHtml(task.timezone || 'default')}</div>
        <div><strong>Enabled:</strong> ${task.enabled ? '✅ Yes' : '❌ No'}</div>
      </div>
      <div class="form-group">
        <label class="form-label">Task Payload</label>
        <div class="code-block" style="white-space: pre-wrap;">${escapeHtml(JSON.stringify(payload, null, 2))}</div>
      </div>
      <div class="form-group">
        <label class="form-label">Schedule</label>
        <div><strong>Original:</strong> ${escapeHtml(payload.when_original || 'n/a')}</div>
        <div><strong>Summary:</strong> ${escapeHtml(payload.schedule_summary || task.schedule_type)}</div>
        <div><strong>Next Run:</strong> ${escapeHtml(formatScheduledNextRun(task.next_run_at))}</div>
        <div class="code-block" style="margin-top: 8px;">${escapeHtml(JSON.stringify(scheduleExpr, null, 2))}</div>
      </div>
      <div class="form-group">
        <label class="form-label">Last Result</label>
        <div><strong>Status:</strong> ${escapeHtml(task.last_status || 'never run')}</div>
        <div><strong>Last Run:</strong> ${escapeHtml(formatDate(task.last_run_at))}</div>
        <div><strong>Duration:</strong> ${task.last_duration_ms ? `${Math.round(task.last_duration_ms)}ms` : 'n/a'}</div>
        ${task.last_error ? `<div><strong>Error:</strong> ${escapeHtml(task.last_error)}</div>` : ''}
        ${task.last_result_summary ? `<div><strong>Summary:</strong> ${escapeHtml(task.last_result_summary)}</div>` : ''}
      </div>
      <div class="form-group">
        <label class="form-label">Recent Runs</label>
        ${runs.length === 0 ? `
          <div class="empty-inline">No run history yet.</div>
        ` : `
          <div class="run-history-list">
            ${runs.map(run => `
              <div class="run-history-item">
                <div class="run-history-head">
                  <strong>${escapeHtml(run.status)}</strong>
                  <span>${escapeHtml(formatDate(run.started_at))}</span>
                </div>
                <div class="run-history-body">
                  ${run.speech ? `<div>${escapeHtml(truncate(run.speech, 200))}</div>` : ''}
                  ${run.error ? `<div class="run-history-error">${escapeHtml(run.error)}</div>` : ''}
                  ${run.tools_used ? `<div class="run-history-meta">Tools: ${escapeHtml(run.tools_used)}</div>` : ''}
                </div>
              </div>
            `).join('')}
          </div>
        `}
      </div>
      <div class="form-group" style="margin-top: var(--space-lg); display: flex; flex-wrap: wrap; gap: var(--space-sm);">
        <button class="btn btn-primary" onclick="editScheduledTask(${task.id}); closeAllModals();">✏️ Edit</button>
        <button class="btn btn-secondary" onclick="runScheduledTaskNow(${task.id});">▶️ Run Now</button>
        <button class="btn btn-secondary" onclick="cancelScheduledTask(${task.id}); closeAllModals();">⏸️ Cancel</button>
        <button class="btn btn-danger" onclick="confirmDeleteScheduledTask(${task.id}); closeAllModals();">🗑️ Delete</button>
      </div>
    `;

    modal.classList.add('active');
  } catch (error) {
    showToast(`Error: ${error.message}`, 'error');
  }
}

async function editScheduledTask(id) {
  try {
    const result = await api.getScheduledTask(id);
    openScheduledTaskModal(result.task);
  } catch (error) {
    showToast(`Error: ${error.message}`, 'error');
  }
}

async function runScheduledTaskNow(id) {
  try {
    await api.runScheduledTaskNow(id);
    showToast('Scheduled task queued to run now', 'success');
    await loadScheduledTasks();
  } catch (error) {
    showToast(`Error: ${error.message}`, 'error');
  }
}

async function toggleScheduledTaskRuns(id) {
  scheduledTaskRunsExpanded[id] = !scheduledTaskRunsExpanded[id];
  renderScheduledTasks();

  if (!scheduledTaskRunsExpanded[id] || scheduledTaskRuns[id]) {
    return;
  }

  scheduledTaskRunsLoading[id] = true;
  renderScheduledTasks();
  try {
    const result = await api.listScheduledTaskRuns(id, 5);
    scheduledTaskRuns[id] = result.runs || [];
  } catch (error) {
    showToast(`Error loading runs: ${error.message}`, 'error');
    scheduledTaskRuns[id] = [];
  } finally {
    scheduledTaskRunsLoading[id] = false;
    renderScheduledTasks();
  }
}

async function cancelScheduledTask(id) {
  if (!confirm('Cancel this scheduled task? You can edit and re-enable it later.')) {
    return;
  }
  try {
    await api.cancelScheduledTask(id);
    showToast('Scheduled task canceled', 'success');
    await loadScheduledTasks();
  } catch (error) {
    showToast(`Error: ${error.message}`, 'error');
  }
}

async function confirmDeleteScheduledTask(id) {
  if (!confirm('Permanently delete this scheduled task and its run history?')) {
    return;
  }
  try {
    await api.deleteScheduledTask(id);
    showToast('Scheduled task deleted', 'success');
    await loadScheduledTasks();
  } catch (error) {
    showToast(`Error: ${error.message}`, 'error');
  }
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
  editingScheduledTask = null;
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

function parseJsonSafe(value) {
  if (!value) return null;
  if (typeof value === 'object') return value;
  try {
    return JSON.parse(value);
  } catch {
    return null;
  }
}

function scheduledTaskMatchesQuery(task, query) {
  const q = query.toLowerCase();
  const payload = parseJsonSafe(task.task_payload) || {};
  return [
    task.name,
    task.task_type,
    task.task_target,
    task.schedule_type,
    task.timezone,
    task.mode,
    task.last_status,
    task.last_error,
    payload.query,
    payload.workflow_id,
    payload.when_original,
    payload.schedule_summary
  ].filter(Boolean).some(value => String(value).toLowerCase().includes(q));
}

function formatRunStatus(status) {
  const normalized = String(status || '').toLowerCase();
  if (!normalized) return 'Never run';
  const labels = {
    success: 'Success',
    failure: 'Failure',
    running: 'Running',
    cancelled: 'Cancelled',
    scheduled: 'Scheduled',
    idle: 'Idle'
  };
  return labels[normalized] || normalized.charAt(0).toUpperCase() + normalized.slice(1);
}

function getRunStatusClass(status) {
  const normalized = String(status || '').toLowerCase();
  if (normalized === 'success') return 'success';
  if (normalized === 'failure') return 'failure';
  if (normalized === 'running') return 'running';
  if (normalized === 'cancelled') return 'cancelled';
  if (normalized === 'scheduled') return 'scheduled';
  return 'neutral';
}

function getScheduledNextRunTimestamp(nextRunAt) {
  if (!nextRunAt) return Number.NaN;
  const value = String(nextRunAt);
  const normalized = /(?:Z|[+-]\d{2}:\d{2})$/.test(value) ? value : `${value}Z`;
  return new Date(normalized).getTime();
}

function formatScheduledNextRun(nextRunAt) {
  if (!nextRunAt) return 'Unknown';
  const ts = getScheduledNextRunTimestamp(nextRunAt);
  if (Number.isNaN(ts)) return String(nextRunAt);
  return new Date(ts).toLocaleString();
}

function getScheduledDueClass(nextRunAt) {
  if (!nextRunAt) return '';
  const nextTs = getScheduledNextRunTimestamp(nextRunAt);
  if (Number.isNaN(nextTs)) return '';
  const diffMs = nextTs - Date.now();
  if (diffMs < 0) return 'due-overdue';
  if (diffMs <= 15 * 60 * 1000) return 'due-urgent';
  if (diffMs <= 60 * 60 * 1000) return 'due-soon';
  return '';
}

function formatScheduledRelativeTime(dateStr) {
  if (!dateStr) return '';
  const ts = getScheduledNextRunTimestamp(dateStr);
  if (Number.isNaN(ts)) return '';

  const diffMs = ts - Date.now();
  const absMs = Math.abs(diffMs);
  const absMinutes = Math.round(absMs / 60000);
  const absHours = Math.round(absMs / 3600000);
  const absDays = Math.round(absMs / 86400000);

  let unit;
  let value;
  if (absMinutes < 60) {
    unit = 'minute';
    value = Math.max(absMinutes, 1);
  } else if (absHours < 48) {
    unit = 'hour';
    value = Math.max(absHours, 1);
  } else {
    unit = 'day';
    value = Math.max(absDays, 1);
  }

  const plural = value === 1 ? unit : `${unit}s`;
  return diffMs >= 0 ? `in ${value} ${plural}` : `${value} ${plural} ago`;
}

function getScheduledLastPreview(task) {
  if (task.last_error) {
    return { kind: 'error', label: 'Last error', text: task.last_error };
  }
  if (task.last_result_summary) {
    return { kind: 'summary', label: 'Last result', text: task.last_result_summary };
  }
  if (task.last_status && task.last_status !== 'running') {
    return { kind: 'status', label: 'Last status', text: formatRunStatus(task.last_status) };
  }
  return null;
}
