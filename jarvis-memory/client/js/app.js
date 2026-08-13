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
let reminders = [];
let alerts = [];
let scheduledTasks = [];
let scheduledTaskWorkflows = [];
let scheduledTaskWorkflowsLoaded = false;
let searchQuery = '';
let editingMemory = null;
let editingFile = null;
let editingReminder = null;
let editingScheduledTask = null;
const DEFAULT_TIMEZONE = Intl.DateTimeFormat().resolvedOptions().timeZone || 'America/Los_Angeles';
let reminderStatusFilter = 'scheduled';
let reminderSortBy = 'trigger_time_asc';
let alertStatusFilter = 'all';
let alertSeverityFilter = 'all';
let scheduledStatusFilter = 'all';
let scheduledSortBy = 'next_run_asc';
let scheduledTaskRuns = {};
let scheduledTaskRunsLoading = {};
let scheduledTaskRunsExpanded = {};
let intelEditorView = 'raw';
let alertTabMonitor = null;
const ALERT_PAGE_SIZE = 100;
let alertOffset = 0;
let alertsHasMore = true;
let alertsLoading = false;
let alertLoadGeneration = 0;

// Search placeholders per tab
const SEARCH_PLACEHOLDERS = {
  memories: 'Search memories (FTS5 or #123)...',
  intel: 'Search intel files...',
  conversations: 'Search conversations...',
  reminders: 'Search reminders...',
  alerts: 'Search alerts...',
  scheduled: 'Search scheduled tasks...',
  stats: 'Search...'
};

// =========================================================================
// Initialization
// =========================================================================

document.addEventListener('DOMContentLoaded', async () => {
  // Runtime data mode: URL override, saved preference, then server startup mode.
  const urlParams = new URLSearchParams(window.location.search);
  const urlMode = urlParams.get('mode');
  const savedMode = localStorage.getItem('jarvis-memory-mode');
  let mode = ['cloud', 'local'].includes(urlMode) ? urlMode : null;
  if (!mode && ['cloud', 'local'].includes(savedMode)) mode = savedMode;
  if (!mode) {
    try {
      const status = await api.getStatus();
      mode = ['cloud', 'local'].includes(status.startup_mode) ? status.startup_mode : 'cloud';
    } catch (_) {
      mode = 'cloud';
    }
  }
  
  document.getElementById('modeSelect').value = mode;
  api.setMode(mode);
  
  // Set up event listeners
  setupEventListeners();
  updateSidebarLayout();

  const requestedTab = window.location.hash.slice(1).toLowerCase();
  const knownTabs = new Set([
    'memories', 'conversations', 'intel', 'reminders', 'alerts', 'scheduled', 'stats'
  ]);
  if (knownTabs.has(requestedTab)) {
    switchTab(requestedTab, { load: false });
  }
  
  // Load initial data
  await loadData();

  // Monitor pending alerts even when another Memory UI tab is active.
  if (window.AlertTabMonitor) {
    alertTabMonitor = new window.AlertTabMonitor({
      api,
      soundButton: document.getElementById('alertSoundToggleBtn'),
      isAlertsViewActive: () => currentTab === 'alerts' && !document.hidden && document.hasFocus(),
      onPendingChange: () => {
        if (currentTab === 'alerts') return loadAlerts();
      },
      onSoundChange: enabled => showToast(`Alert sound ${enabled ? 'on' : 'off'}`, 'success'),
      onSoundUnavailable: () => showToast('Alert sound is not available in this browser', 'error')
    });
    alertTabMonitor.setControlVisible(currentTab === 'alerts');
    await alertTabMonitor.init();
    window.addEventListener('beforeunload', () => alertTabMonitor?.destroy(), { once: true });
  }
});

function setupEventListeners() {
  // Mode selector
  document.getElementById('modeSelect').addEventListener('change', async (e) => {
    const mode = e.target.value;
    api.setMode(mode);
    localStorage.setItem('jarvis-memory-mode', mode);
    await alertTabMonitor?.reset();
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
  document.getElementById('addReminderBtn')?.addEventListener('click', () => openReminderModal());
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
  document.getElementById('reminderForm').addEventListener('submit', handleReminderSubmit);
  document.getElementById('reminderRecurrenceType')?.addEventListener('change', handleReminderRecurrenceChange);
  document.getElementById('reminderTriggerTime')?.addEventListener('change', syncReminderRecurrenceDefaultsFromTrigger);
  
  // Intel file form
  document.getElementById('intelForm').addEventListener('submit', handleIntelSubmit);
  document.getElementById('intelContent')?.addEventListener('input', updateIntelRenderedPreview);
  document.getElementById('intelEditorRawBtn')?.addEventListener('click', () => setIntelEditorView('raw'));
  document.getElementById('intelEditorRenderedBtn')?.addEventListener('click', () => setIntelEditorView('rendered'));
  document.getElementById('scheduledTaskForm').addEventListener('submit', handleScheduledTaskSubmit);
  document.getElementById('scheduledTaskType')?.addEventListener('change', handleScheduledTaskTypeChange);
  document.getElementById('scheduledTaskWorkflowId')?.addEventListener('change', updateScheduledTaskWorkflowDetails);
  document.getElementById('scheduledTaskDateTime')?.addEventListener('change', syncScheduledTaskWhenFromDateTime);
  document.getElementById('scheduledStatusFilter')?.addEventListener('change', (e) => {
    scheduledStatusFilter = e.target.value;
    renderScheduledTasks();
  });
  document.getElementById('scheduledSortBy')?.addEventListener('change', (e) => {
    scheduledSortBy = e.target.value;
    renderScheduledTasks();
  });
  document.getElementById('reminderStatusFilter')?.addEventListener('change', (e) => {
    reminderStatusFilter = e.target.value;
    renderReminders();
  });
  document.getElementById('reminderSortBy')?.addEventListener('change', (e) => {
    reminderSortBy = e.target.value;
    renderReminders();
  });
  document.getElementById('ackTriggeredRemindersBtn')?.addEventListener('click', acknowledgeTriggeredReminders);
  document.getElementById('alertStatusFilter')?.addEventListener('change', (e) => {
    alertStatusFilter = e.target.value;
    resetAlertListScroll();
    loadAlerts();
  });
  document.getElementById('alertSeverityFilter')?.addEventListener('change', (e) => {
    alertSeverityFilter = e.target.value;
    resetAlertListScroll();
    loadAlerts();
  });
  document.getElementById('ackPendingAlertsBtn')?.addEventListener('click', acknowledgePendingAlerts);
  document.getElementById('alertList')?.addEventListener('scroll', handleAlertListScroll);
  
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
    } else if (currentTab === 'reminders') {
      await loadReminders();
    } else if (currentTab === 'alerts') {
      await loadAlerts();
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

async function loadReminders() {
  try {
    const result = await api.listReminders({ status: 'all', limit: 300 });
    reminders = result.reminders || [];
    renderReminders();
  } catch (error) {
    console.error('Error loading reminders:', error);
    reminders = [];
    renderReminders();
  }
}

async function loadAlerts({ append = false } = {}) {
  if (append && (!alertsHasMore || alertsLoading)) return;

  const generation = append ? alertLoadGeneration : ++alertLoadGeneration;
  if (!append) {
    alertOffset = 0;
    alertsHasMore = true;
  }
  alertsLoading = true;

  try {
    const result = await api.listAlerts({
      status: alertStatusFilter,
      severity: alertSeverityFilter,
      search: searchQuery,
      limit: ALERT_PAGE_SIZE,
      offset: append ? alertOffset : 0
    });
    if (generation !== alertLoadGeneration) return;

    const page = result.alerts || [];
    if (append) {
      const knownIds = new Set(alerts.map(alert => String(alert.id)));
      alerts = alerts.concat(page.filter(alert => !knownIds.has(String(alert.id))));
    } else {
      alerts = page;
    }
    alertOffset = result.next_offset ?? (alertOffset + page.length);
    alertsHasMore = result.has_more ?? page.length === ALERT_PAGE_SIZE;
  } catch (error) {
    console.error('Error loading alerts:', error);
    if (!append && generation === alertLoadGeneration) alerts = [];
    if (generation === alertLoadGeneration) alertsHasMore = false;
  } finally {
    if (generation === alertLoadGeneration) {
      alertsLoading = false;
      renderAlerts();
    }
  }
}

function handleAlertListScroll(event) {
  const container = event.currentTarget;
  const remaining = container.scrollHeight - container.scrollTop - container.clientHeight;
  if (remaining < 240) loadAlerts({ append: true });
}

function resetAlertListScroll() {
  const container = document.getElementById('alertList');
  if (container) container.scrollTop = 0;
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

/**
 * Intel ingest stores per-file MD5 fingerprints (keys intel_hash_*.md) with no embedding on purpose.
 * They must not show "missing embedding" warnings or Re-embed — not a semantic memory row.
 */
function isIntelIngestHashRecord(memory) {
  if (!memory) return false;
  const cat = (memory.category || '').toLowerCase();
  const key = memory.key || '';
  return cat === 'system' && key.startsWith('intel_hash_');
}

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
        <div class="memory-card-header-badges">
          <span class="memory-id-badge" title="Memory ID for current mode">#${memory.id}</span>
          <span class="memory-category">${escapeHtml(memory.category)}</span>
        </div>
      </div>
      <div class="memory-value">${escapeHtml(memory.value)}</div>
      <div class="memory-card-footer">
        <div class="memory-meta">
          <span title="Importance"><span class="importance-badge ${importanceClass}">${memory.importance}</span></span>
          <span title="Size: ${valueLength} chars">${sizeIndicator}</span>
          <span title="Updated">${updatedDate}</span>
          ${memory.has_embedding
            ? '<span title="Has embedding - semantic search enabled">🔮</span>'
            : isIntelIngestHashRecord(memory)
              ? '<span title="Intel ingest file hash (not embedded by design)">📌</span>'
              : '<span title="No embedding - keyword search only">⚪</span>'}
          ${healthStatus.icon ? `<span title="${healthStatus.message}">${healthStatus.icon}</span>` : ''}
        </div>
        <div class="memory-actions">
          ${!memory.has_embedding && !isIntelIngestHashRecord(memory) ? `<button class="btn btn-icon" onclick="event.stopPropagation(); reembedMemory(${memory.id})" title="Generate embedding">🔮</button>` : ''}
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

function renderReminders() {
  const container = document.getElementById('reminderList');
  const filteredReminders = getVisibleReminders();

  if (filteredReminders.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <div class="empty-state-icon">⏰</div>
        <div class="empty-state-title">${searchQuery ? 'No reminders found' : 'No reminders yet'}</div>
        <div class="empty-state-desc">${searchQuery || reminderStatusFilter !== 'all' ? 'Try a different search term or filter' : 'Create a reminder to track what is pending, triggered, or acknowledged'}</div>
        ${!searchQuery ? '<button class="btn btn-primary" onclick="openReminderModal()">+ Add Reminder</button>' : ''}
      </div>
    `;
    return;
  }

  container.innerHTML = `
    <div class="memory-grid">
      ${filteredReminders.map(reminder => renderReminderCard(reminder)).join('')}
    </div>
  `;
}

function renderReminderCard(reminder) {
  const status = String(reminder.status || 'scheduled').toLowerCase();
  const triggerLocal = formatReminderTriggerLocal(reminder.trigger_time);
  const relative = formatReminderRelativeTime(reminder.trigger_time);
  const dueClass = getReminderDueClass(reminder);
  const preview = getReminderPreview(reminder);
  const metadata = parseJsonSafe(reminder.metadata) || {};

  return `
    <div class="memory-card reminder-card ${dueClass}" onclick="viewReminder(${reminder.id})">
      <div class="memory-card-header">
        <div>
          <div class="memory-key">${escapeHtml(reminder.title || `Reminder ${reminder.id}`)}</div>
          <div class="scheduled-task-subtitle">${escapeHtml(triggerLocal)}</div>
        </div>
        <div class="scheduled-task-badges">
          <span class="status-badge run-status ${getReminderStatusClass(status)}">${escapeHtml(formatReminderStatus(status))}</span>
          ${reminder.spoken ? '<span class="status-badge enabled">Spoken</span>' : ''}
        </div>
      </div>
      <div class="memory-value">${escapeHtml(truncate(preview, 180))}</div>
      <div class="scheduled-next-run">
        <span class="scheduled-next-run-label">Trigger time</span>
        <span class="scheduled-next-run-value">${escapeHtml(triggerLocal)}</span>
        ${relative ? `<span class="scheduled-next-run-relative">${escapeHtml(relative)}</span>` : ''}
      </div>
      <div class="memory-card-footer">
        <div class="memory-meta">
          <span title="Status">📌 ${escapeHtml(formatReminderStatus(status))}</span>
          ${reminder.created_at ? `<span title="Created">🕘 ${escapeHtml(formatDate(reminder.created_at))}</span>` : ''}
          ${metadata?.gcal_event_id ? '<span title="Google Calendar synced">📅 GCal</span>' : ''}
          ${reminder.callback_url ? '<span title="Has callback URL">🔗 Webhook</span>' : ''}
        </div>
        <div class="memory-actions">
          ${status === 'triggered' ? `<button class="btn btn-icon" onclick="event.stopPropagation(); acknowledgeReminder(${reminder.id})" title="Acknowledge">✅</button>` : ''}
          <button class="btn btn-icon" onclick="event.stopPropagation(); editReminder(${reminder.id})" title="Edit">✏️</button>
          ${status === 'scheduled' ? `<button class="btn btn-icon" onclick="event.stopPropagation(); cancelReminder(${reminder.id})" title="Cancel">⏸️</button>` : ''}
          <button class="btn btn-icon" onclick="event.stopPropagation(); confirmDeleteReminder(${reminder.id})" title="Delete">🗑️</button>
        </div>
      </div>
    </div>
  `;
}

function renderAlerts() {
  const container = document.getElementById('alertList');
  const filteredAlerts = getVisibleAlerts();

  if (filteredAlerts.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <div class="empty-state-icon">🚨</div>
        <div class="empty-state-title">${searchQuery ? 'No alerts found' : 'No alerts yet'}</div>
        <div class="empty-state-desc">${searchQuery || alertStatusFilter !== 'all' || alertSeverityFilter !== 'all' ? 'Try a different search term or filter' : 'Workflow and webhook alerts will appear here'}</div>
      </div>
    `;
    return;
  }

  container.innerHTML = `
    <div class="memory-grid">
      ${filteredAlerts.map(alert => renderAlertCard(alert)).join('')}
    </div>
    ${alertsHasMore ? `
      <div class="alert-pagination-status">
        ${alertsLoading ? '<span class="spinner"></span> Loading older alerts...' : 'Scroll for older alerts'}
      </div>
    ` : alerts.length > 0 ? '<div class="alert-pagination-status">All matching alerts loaded</div>' : ''}
  `;
}

function renderAlertCard(alert) {
  const status = String(alert.status || 'pending').toLowerCase();
  const severity = String(alert.severity || 'medium').toLowerCase();
  const preview = getAlertPreview(alert);

  return `
    <div class="memory-card alert-card" onclick="viewAlert(${alert.id})">
      <div class="memory-card-header">
        <div>
          <div class="memory-key">${escapeHtml(alert.title || `Alert ${alert.id}`)}</div>
          <div class="scheduled-task-subtitle">${escapeHtml(alert.source || 'unknown source')}</div>
        </div>
        <div class="scheduled-task-badges">
          <span class="status-badge alert-severity ${escapeHtml(severity)}">${escapeHtml(formatAlertSeverity(severity))}</span>
          <span class="status-badge run-status ${getAlertStatusClass(status)}">${escapeHtml(formatAlertStatus(status))}</span>
        </div>
      </div>
      <div class="memory-value">${escapeHtml(truncate(preview, 180))}</div>
      <div class="scheduled-next-run">
        <span class="scheduled-next-run-label">Created</span>
        <span class="scheduled-next-run-value">${escapeHtml(formatDate(alert.created_at))}</span>
        ${alert.acknowledged_at ? `<span class="scheduled-next-run-relative">Acknowledged ${escapeHtml(formatDate(alert.acknowledged_at))}</span>` : ''}
      </div>
      <div class="memory-card-footer">
        <div class="memory-meta">
          <span title="Severity">🚨 ${escapeHtml(formatAlertSeverity(severity))}</span>
          <span title="Status">📌 ${escapeHtml(formatAlertStatus(status))}</span>
          ${alert.spoken ? '<span title="Spoken immediately">🔊 Spoken</span>' : ''}
          ${alert.related_intel_file ? '<span title="Related intel file">📁 Intel</span>' : ''}
        </div>
        <div class="memory-actions">
          ${status === 'pending' ? `<button class="btn btn-icon" onclick="event.stopPropagation(); acknowledgeAlert(${alert.id})" title="Acknowledge">✅</button>` : ''}
          ${status === 'pending' ? `<button class="btn btn-icon" onclick="event.stopPropagation(); cancelAlert(${alert.id})" title="Cancel">⏸️</button>` : ''}
        </div>
      </div>
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
                    ${renderScheduledRunNotifications(run)}
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
  if (hasActiveModal()) return;

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

function hasActiveModal() {
  return !!document.querySelector('.modal-overlay.active');
}

function setModalOpenState(isOpen) {
  document.getElementById('app')?.classList.toggle('modal-open', isOpen);
}

function showModal(modal) {
  if (!modal) return;
  closeSidebar();
  modal.classList.add('active');
  setModalOpenState(true);
}

// =========================================================================
// Tab Navigation
// =========================================================================

function switchTab(tab, { load = true } = {}) {
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
  updateSidebarLayout();
  
  // Update toolbar buttons
  document.getElementById('addMemoryBtn').style.display = tab === 'memories' ? 'flex' : 'none';
  document.getElementById('addIntelBtn').style.display = tab === 'intel' ? 'flex' : 'none';
  document.getElementById('addReminderBtn').style.display = tab === 'reminders' ? 'flex' : 'none';
  document.getElementById('addScheduledTaskBtn').style.display = tab === 'scheduled' ? 'flex' : 'none';
  document.getElementById('uploadIntelBtn').style.display = tab === 'intel' ? 'flex' : 'none';
  document.getElementById('ingestIntelBtn').style.display = tab === 'intel' ? 'flex' : 'none';
  alertTabMonitor?.setControlVisible(tab === 'alerts');
  if (tab === 'alerts') alertTabMonitor?.acknowledgeAttention();
  
  // Load data for tab
  if (load) loadData();
}

function updateSidebarLayout() {
  const app = document.getElementById('app');
  const sidebar = document.querySelector('.sidebar');
  const sidebarVisible = currentTab === 'memories';

  if (sidebar) {
    sidebar.style.display = sidebarVisible ? 'flex' : 'none';
  }

  app?.classList.toggle('has-desktop-sidebar', sidebarVisible);
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

function getVisibleReminders() {
  let items = [...reminders];

  if (searchQuery) {
    items = items.filter(reminder => reminderMatchesQuery(reminder, searchQuery));
  }

  items = items.filter(reminder => matchesReminderStatusFilter(reminder, reminderStatusFilter));
  items.sort((a, b) => compareReminders(a, b, reminderSortBy));
  return items;
}

function getVisibleAlerts() {
  let items = [...alerts];

  if (searchQuery) {
    items = items.filter(alert => alertMatchesQuery(alert, searchQuery));
  }

  items = items.filter(alert => matchesAlertStatusFilter(alert, alertStatusFilter));
  items = items.filter(alert => matchesAlertSeverityFilter(alert, alertSeverityFilter));
  items.sort((a, b) => compareAlerts(a, b));
  return items;
}

function matchesReminderStatusFilter(reminder, filter) {
  if (filter === 'all') return true;
  return String(reminder.status || '').toLowerCase() === filter;
}

function matchesAlertStatusFilter(alert, filter) {
  if (filter === 'all') return true;
  return String(alert.status || '').toLowerCase() === filter;
}

function matchesAlertSeverityFilter(alert, filter) {
  if (filter === 'all') return true;
  return String(alert.severity || '').toLowerCase() === filter;
}

function compareReminders(a, b, sortBy) {
  const aTrigger = getReminderTriggerTimestamp(a.trigger_time);
  const bTrigger = getReminderTriggerTimestamp(b.trigger_time);
  const aCreated = a.created_at ? new Date(a.created_at).getTime() : 0;
  const bCreated = b.created_at ? new Date(b.created_at).getTime() : 0;

  switch (sortBy) {
    case 'trigger_time_desc':
      return bTrigger - aTrigger;
    case 'created_desc':
      return bCreated - aCreated;
    case 'title_asc':
      return String(a.title || '').localeCompare(String(b.title || ''));
    case 'status_asc':
      return formatReminderStatus(a.status).localeCompare(formatReminderStatus(b.status));
    case 'trigger_time_asc':
    default:
      return aTrigger - bTrigger;
  }
}

function compareAlerts(a, b) {
  const aCreated = a.created_at ? new Date(a.created_at).getTime() : 0;
  const bCreated = b.created_at ? new Date(b.created_at).getTime() : 0;
  return bCreated - aCreated;
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
  
  showModal(modal);
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
          <div><strong>Embedding:</strong> ${
            memory.has_embedding
              ? '✅ Yes'
              : isIntelIngestHashRecord(memory)
                ? '➖ Skipped (intel file fingerprint)'
                : '❌ No'
          }</div>
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
      ${!memory.has_embedding && !isIntelIngestHashRecord(memory) ? `
      <div class="form-group" style="background: var(--warning-bg); padding: var(--space-md); border-radius: var(--radius-md); border-left: 3px solid var(--warning);">
        <strong>⚠️ No Embedding</strong><br>
        This memory won't appear in semantic search. Click "🔮 Re-embed" to generate an embedding.
      </div>
      ` : ''}
      ${!memory.has_embedding && isIntelIngestHashRecord(memory) ? `
      <div class="form-group" style="background: var(--bg-tertiary); padding: var(--space-md); border-radius: var(--radius-md); border-left: 3px solid var(--border-secondary);">
        <strong>Intel ingest fingerprint</strong><br>
        This row stores the MD5 of an intel file so re-ingest can skip unchanged files. It is not meant to be embedded or appear in semantic search.
      </div>
      ` : ''}
      <div class="form-group" style="margin-top: var(--space-lg); display: flex; flex-wrap: wrap; gap: var(--space-sm);">
        <button class="btn btn-primary" onclick="editMemory(${memory.id}); closeAllModals();">✏️ Edit</button>
        ${!isIntelIngestHashRecord(memory) ? `<button class="btn btn-secondary" onclick="reembedMemory(${memory.id});" title="Re-generate embedding for semantic search">🔮 Re-embed</button>` : ''}
        <button class="btn btn-danger" onclick="confirmDeleteMemory(${memory.id}); closeAllModals();">🗑️ Delete</button>
      </div>
    `;
    
    showModal(modal);
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
  intelEditorView = 'raw';
  updateIntelRenderedPreview();
  setIntelEditorView('raw');
  
  showModal(modal);
}

function openReminderModal(reminder = null) {
  editingReminder = reminder;

  const modal = document.getElementById('reminderModal');
  const title = document.getElementById('reminderModalTitle');
  const recurrence = parseReminderRecurrenceRule(reminder?.recurrence_rule, reminder?.trigger_time);

  title.textContent = reminder ? 'Edit Reminder' : 'Add Reminder';

  document.getElementById('reminderTitle').value = reminder?.title || '';
  document.getElementById('reminderDescription').value = reminder?.description || '';
  document.getElementById('reminderTriggerTime').value = reminder?.trigger_time ? formatReminderForDateTimeInput(reminder.trigger_time) : '';
  document.getElementById('reminderRecurrenceType').value = recurrence.type;
  document.getElementById('reminderWeeklyDay').value = String(recurrence.weekday ?? 0);
  document.getElementById('reminderMonthlyDay').value = String(recurrence.day ?? 1);
  document.getElementById('reminderIntelFile').value = reminder?.related_intel_file || '';
  document.getElementById('reminderCallbackUrl').value = reminder?.callback_url || '';

  handleReminderRecurrenceChange();
  if (!reminder) {
    syncReminderRecurrenceDefaultsFromTrigger();
  }
  showModal(modal);
}

function handleReminderRecurrenceChange() {
  const type = document.getElementById('reminderRecurrenceType').value;
  document.getElementById('reminderWeeklyRow').style.display = type === 'weekly' ? 'grid' : 'none';
  document.getElementById('reminderMonthlyRow').style.display = type === 'monthly' ? 'grid' : 'none';
}

function syncReminderRecurrenceDefaultsFromTrigger() {
  const triggerValue = document.getElementById('reminderTriggerTime').value;
  if (!triggerValue) return;
  const local = new Date(triggerValue);
  if (Number.isNaN(local.getTime())) return;
  const jsDay = local.getDay(); // 0=Sun..6=Sat
  const weeklyDay = (jsDay + 6) % 7; // 0=Mon..6=Sun
  document.getElementById('reminderWeeklyDay').value = String(weeklyDay);
  document.getElementById('reminderMonthlyDay').value = String(local.getDate());
}

async function handleReminderSubmit(e) {
  e.preventDefault();

  const triggerValue = document.getElementById('reminderTriggerTime').value;
  const triggerTimeUtc = localDateTimeInputToUtcDb(triggerValue);
  if (!triggerTimeUtc) {
    showToast('Trigger time is required', 'error');
    return;
  }

  const data = {
    title: document.getElementById('reminderTitle').value.trim(),
    description: document.getElementById('reminderDescription').value.trim() || null,
    trigger_time: triggerTimeUtc,
    recurrence_rule: buildReminderRecurrenceRule(),
    related_intel_file: document.getElementById('reminderIntelFile').value.trim() || null,
    callback_url: document.getElementById('reminderCallbackUrl').value.trim() || null
  };

  if (!data.title) {
    showToast('Reminder title is required', 'error');
    return;
  }

  try {
    if (editingReminder) {
      await api.updateReminder(editingReminder.id, data);
      showToast('Reminder updated', 'success');
    } else {
      await api.createReminder(data);
      showToast('Reminder created', 'success');
    }
    closeAllModals();
    await loadReminders();
  } catch (error) {
    showToast(`Error: ${error.message}`, 'error');
  }
}

async function viewReminder(id) {
  try {
    const result = await api.getReminder(id);
    const reminder = result.reminder;
    const metadata = parseJsonSafe(reminder.metadata) || reminder.metadata;
    const modal = document.getElementById('reminderDetailModal');
    const content = document.getElementById('reminderDetailContent');
    const status = String(reminder.status || 'scheduled').toLowerCase();

    content.innerHTML = `
      <div class="form-group">
        <label class="form-label">Title</label>
        <div class="code-block">${escapeHtml(reminder.title || '')}</div>
      </div>
      ${reminder.description ? `
      <div class="form-group">
        <label class="form-label">Description</label>
        <div class="code-block" style="white-space: pre-wrap;">${escapeHtml(reminder.description)}</div>
      </div>
      ` : ''}
      <div class="form-group">
        <label class="form-label">Timing</label>
        <div><strong>Trigger time:</strong> ${escapeHtml(formatReminderTriggerLocal(reminder.trigger_time))}</div>
        <div><strong>Relative:</strong> ${escapeHtml(formatReminderRelativeTime(reminder.trigger_time) || 'n/a')}</div>
        <div><strong>Status:</strong> ${escapeHtml(formatReminderStatus(status))}</div>
        ${reminder.recurrence_rule ? `<div><strong>Recurrence:</strong> ${escapeHtml(formatReminderRecurrence(reminder.recurrence_rule, reminder.trigger_time))} <span style="color: var(--text-muted);">(${escapeHtml(reminder.recurrence_rule)})</span></div>` : ''}
      </div>
      <div class="form-group">
        <label class="form-label">Lifecycle</label>
        <div><strong>Created:</strong> ${escapeHtml(formatDate(reminder.created_at))}</div>
        ${reminder.triggered_at ? `<div><strong>Triggered:</strong> ${escapeHtml(formatDate(reminder.triggered_at))}</div>` : ''}
        ${reminder.acknowledged_at ? `<div><strong>Acknowledged:</strong> ${escapeHtml(formatDate(reminder.acknowledged_at))}</div>` : ''}
        ${reminder.spoken_at ? `<div><strong>Spoken at:</strong> ${escapeHtml(formatDate(reminder.spoken_at))}</div>` : ''}
        <div><strong>Spoken:</strong> ${reminder.spoken ? '✅ Yes' : '❌ No'}</div>
      </div>
      ${reminder.related_intel_file || reminder.callback_url ? `
      <div class="form-group">
        <label class="form-label">Links</label>
        ${reminder.related_intel_file ? `<div><strong>Intel file:</strong> ${escapeHtml(reminder.related_intel_file)}</div>` : ''}
        ${reminder.callback_url ? `<div><strong>Callback URL:</strong> ${escapeHtml(reminder.callback_url)}</div>` : ''}
      </div>
      ` : ''}
      ${metadata ? `
      <div class="form-group">
        <label class="form-label">Metadata</label>
        <div class="code-block" style="white-space: pre-wrap;">${escapeHtml(typeof metadata === 'string' ? metadata : JSON.stringify(metadata, null, 2))}</div>
      </div>
      ` : ''}
      <div class="form-group" style="margin-top: var(--space-lg); display: flex; flex-wrap: wrap; gap: var(--space-sm);">
        ${status === 'triggered' ? `<button class="btn btn-primary" onclick="acknowledgeReminder(${reminder.id}); closeAllModals();">✅ Acknowledge</button>` : ''}
        <button class="btn btn-primary" onclick="editReminder(${reminder.id}); closeAllModals();">✏️ Edit</button>
        ${status === 'scheduled' ? `<button class="btn btn-secondary" onclick="cancelReminder(${reminder.id}); closeAllModals();">⏸️ Cancel</button>` : ''}
        <button class="btn btn-danger" onclick="confirmDeleteReminder(${reminder.id}); closeAllModals();">🗑️ Delete</button>
      </div>
    `;

    showModal(modal);
  } catch (error) {
    showToast(`Error: ${error.message}`, 'error');
  }
}

async function editReminder(id) {
  try {
    const result = await api.getReminder(id);
    openReminderModal(result.reminder);
  } catch (error) {
    showToast(`Error: ${error.message}`, 'error');
  }
}

async function acknowledgeReminder(id) {
  try {
    await api.acknowledgeReminder(id);
    showToast('Reminder acknowledged', 'success');
    await loadReminders();
  } catch (error) {
    showToast(`Error: ${error.message}`, 'error');
  }
}

async function acknowledgeTriggeredReminders() {
  if (!confirm('Acknowledge all currently triggered reminders?')) {
    return;
  }
  try {
    const result = await api.acknowledgeAllReminders('triggered');
    showToast(result.message || 'Triggered reminders acknowledged', 'success');
    await loadReminders();
  } catch (error) {
    showToast(`Error: ${error.message}`, 'error');
  }
}

async function cancelReminder(id) {
  if (!confirm('Cancel this reminder?')) {
    return;
  }
  try {
    await api.cancelReminder(id);
    showToast('Reminder canceled', 'success');
    await loadReminders();
  } catch (error) {
    showToast(`Error: ${error.message}`, 'error');
  }
}

async function confirmDeleteReminder(id) {
  if (!confirm('Permanently delete this reminder?')) {
    return;
  }
  try {
    await api.deleteReminder(id);
    showToast('Reminder deleted', 'success');
    await loadReminders();
  } catch (error) {
    showToast(`Error: ${error.message}`, 'error');
  }
}

async function viewAlert(id) {
  try {
    const result = await api.getAlert(id);
    const alert = result.alert;
    const metadata = parseJsonSafe(alert.metadata) || alert.metadata;
    const modal = document.getElementById('viewModal');
    const content = document.getElementById('viewContent');
    const status = String(alert.status || 'pending').toLowerCase();
    const severity = String(alert.severity || 'medium').toLowerCase();

    content.innerHTML = `
      <div class="form-group">
        <label class="form-label">Title</label>
        <div class="code-block">${escapeHtml(alert.title || '')}</div>
      </div>
      ${alert.description ? `
      <div class="form-group">
        <label class="form-label">Description</label>
        <div class="code-block" style="white-space: pre-wrap;">${escapeHtml(alert.description)}</div>
      </div>
      ` : ''}
      <div class="form-group">
        <label class="form-label">Status</label>
        <div><strong>Severity:</strong> ${escapeHtml(formatAlertSeverity(severity))}</div>
        <div><strong>Status:</strong> ${escapeHtml(formatAlertStatus(status))}</div>
        <div><strong>Source:</strong> ${escapeHtml(alert.source || 'unknown')}</div>
        <div><strong>Spoken:</strong> ${alert.spoken ? '✅ Yes' : '❌ No'}</div>
      </div>
      <div class="form-group">
        <label class="form-label">Timestamps</label>
        <div><strong>Created:</strong> ${escapeHtml(formatDate(alert.created_at))}</div>
        ${alert.updated_at ? `<div><strong>Updated:</strong> ${escapeHtml(formatDate(alert.updated_at))}</div>` : ''}
        ${alert.acknowledged_at ? `<div><strong>Acknowledged:</strong> ${escapeHtml(formatDate(alert.acknowledged_at))}</div>` : ''}
        ${alert.resolved_at ? `<div><strong>Resolved:</strong> ${escapeHtml(formatDate(alert.resolved_at))}</div>` : ''}
        ${alert.spoken_at ? `<div><strong>Spoken at:</strong> ${escapeHtml(formatDate(alert.spoken_at))}</div>` : ''}
      </div>
      ${alert.auto_resolve_url || alert.related_intel_file ? `
      <div class="form-group">
        <label class="form-label">Links</label>
        ${alert.auto_resolve_url ? `<div><strong>Auto-resolve URL:</strong> ${escapeHtml(alert.auto_resolve_url)}</div>` : ''}
        ${alert.related_intel_file ? `<div><strong>Related intel file:</strong> ${escapeHtml(alert.related_intel_file)}</div>` : ''}
      </div>
      ` : ''}
      ${metadata ? `
      <div class="form-group">
        <label class="form-label">Metadata</label>
        <div class="code-block" style="white-space: pre-wrap;">${escapeHtml(typeof metadata === 'string' ? metadata : JSON.stringify(metadata, null, 2))}</div>
      </div>
      ` : ''}
      <div class="form-group" style="margin-top: var(--space-lg); display: flex; flex-wrap: wrap; gap: var(--space-sm);">
        ${status === 'pending' ? `<button class="btn btn-primary" onclick="acknowledgeAlert(${alert.id}); closeAllModals();">✅ Acknowledge</button>` : ''}
        ${status === 'pending' ? `<button class="btn btn-secondary" onclick="cancelAlert(${alert.id}); closeAllModals();">⏸️ Cancel</button>` : ''}
      </div>
    `;

    showModal(modal);
  } catch (error) {
    showToast(`Error: ${error.message}`, 'error');
  }
}

async function acknowledgeAlert(id) {
  try {
    await api.acknowledgeAlert(id);
    showToast('Alert acknowledged', 'success');
    await loadAlerts();
    await alertTabMonitor?.check({ force: true });
  } catch (error) {
    showToast(`Error: ${error.message}`, 'error');
  }
}

async function acknowledgePendingAlerts() {
  if (!confirm('Acknowledge all currently pending alerts?')) {
    return;
  }
  try {
    const result = await api.acknowledgeAllAlerts('pending');
    showToast(result.message || 'Pending alerts acknowledged', 'success');
    await loadAlerts();
    await alertTabMonitor?.check({ force: true });
  } catch (error) {
    showToast(`Error: ${error.message}`, 'error');
  }
}

async function cancelAlert(id) {
  if (!confirm('Cancel this alert?')) {
    return;
  }
  try {
    await api.cancelAlert(id);
    showToast('Alert canceled', 'success');
    await loadAlerts();
    await alertTabMonitor?.check({ force: true });
  } catch (error) {
    showToast(`Error: ${error.message}`, 'error');
  }
}

async function loadScheduledTaskWorkflows(force = false) {
  if (scheduledTaskWorkflowsLoaded && !force) {
    return scheduledTaskWorkflows;
  }

  const result = await api.listScheduledTaskWorkflows();
  scheduledTaskWorkflows = result.workflows || [];
  scheduledTaskWorkflowsLoaded = true;
  return scheduledTaskWorkflows;
}

function formatWorkflowOptionLabel(workflow) {
  const name = workflow.name || workflow.id;
  return name === workflow.id ? workflow.id : `${name} (${workflow.id})`;
}

function renderScheduledTaskWorkflowOptions(selectedId = '') {
  const select = document.getElementById('scheduledTaskWorkflowId');
  if (!select) return;

  const workflows = scheduledTaskWorkflows || [];
  const selectedKnown = workflows.some(workflow => workflow.id === selectedId);
  const options = [
    '<option value="">Select a workflow...</option>',
    ...workflows.map(workflow => {
      const triggers = (workflow.triggers || []).join(', ');
      const title = [workflow.description, triggers ? `Triggers: ${triggers}` : null]
        .filter(Boolean)
        .join(' | ');
      return `<option value="${escapeHtml(workflow.id)}" title="${escapeHtml(title)}">${escapeHtml(formatWorkflowOptionLabel(workflow))}</option>`;
    })
  ];

  if (selectedId && !selectedKnown) {
    options.push(`<option value="${escapeHtml(selectedId)}">${escapeHtml(selectedId)} (not currently loaded)</option>`);
  }
  if (!workflows.length && !selectedId) {
    options[0] = '<option value="">No workflows loaded</option>';
  }

  select.innerHTML = options.join('');
  select.value = selectedId;
  updateScheduledTaskWorkflowDetails();
}

function updateScheduledTaskWorkflowDetails() {
  const select = document.getElementById('scheduledTaskWorkflowId');
  const details = document.getElementById('scheduledTaskWorkflowDetails');
  if (!select || !details) return;

  const workflowId = select.value;
  const workflow = (scheduledTaskWorkflows || []).find(item => item.id === workflowId);
  const queryLabel = document.getElementById('scheduledTaskQueryLabel');
  const queryInput = document.getElementById('scheduledTaskQuery');
  const isWorkflowTask = document.getElementById('scheduledTaskType')?.value === 'workflow';
  if (isWorkflowTask && queryLabel && queryInput) {
    queryLabel.textContent = workflow?.requires_input ? 'Workflow Input *' : 'Workflow Input';
    const inputNames = (workflow?.input_fields || []).map(field => field.name).join(', ');
    queryInput.placeholder = inputNames
      ? `Provide ${inputNames}, such as a URL, topic, host, or note text`
      : 'Optional URL, topic, host, or parameters for the workflow';
  }
  if (!workflow) {
    details.style.display = workflowId ? 'block' : 'none';
    details.innerHTML = workflowId
      ? `<div class="workflow-detail-title">${escapeHtml(workflowId)}</div><div class="workflow-detail-muted">This workflow is not currently loaded from data/workflows or data/workflows/personal.</div>`
      : '';
    return;
  }

  const triggers = (workflow.triggers || []).join(', ') || workflow.trigger || `/${workflow.id}`;
  const tools = (workflow.tools_used || []).slice(0, 10).join(', ') || 'No tools listed';
  const inputFields = workflow.input_fields || [];
  const inputSummary = inputFields.length
    ? inputFields.map(field => {
      const label = field.extract ? `${field.name} (${field.extract})` : field.name;
      return field.required ? `${label} required` : `${label} optional`;
    }).join(', ')
    : 'None';
  details.style.display = 'block';
  details.innerHTML = `
    <div class="workflow-detail-title">${escapeHtml(workflow.name || workflow.id)}</div>
    ${workflow.description ? `<div class="workflow-detail-desc">${escapeHtml(workflow.description)}</div>` : ''}
    <div class="workflow-detail-grid">
      <div><strong>ID:</strong> <code>${escapeHtml(workflow.id)}</code></div>
      <div><strong>Trigger:</strong> <code>${escapeHtml(triggers)}</code></div>
      <div><strong>Input:</strong> ${escapeHtml(inputSummary)}</div>
      <div><strong>Tools:</strong> ${escapeHtml(tools)}</div>
    </div>
  `;
}

async function openScheduledTaskModal(task = null) {
  editingScheduledTask = task;

  const modal = document.getElementById('scheduledTaskModal');
  const title = document.getElementById('scheduledTaskModalTitle');
  const payload = parseJsonSafe(task?.task_payload) || {};
  const metadata = parseJsonSafe(task?.metadata) || {};
  const notifications = metadata.notifications || {};
  const selectedWorkflowId = task?.task_target || payload.workflow_id || '';

  title.textContent = task ? 'Edit Scheduled Task' : 'Add Scheduled Task';

  document.getElementById('scheduledTaskName').value = task?.name || '';
  document.getElementById('scheduledTaskType').value = task?.task_type || 'query';
  document.getElementById('scheduledTaskQuery').value = payload.query || '';
  renderScheduledTaskWorkflowOptions(selectedWorkflowId);
  document.getElementById('scheduledTaskWhen').value = payload.when_original || '';
  document.getElementById('scheduledTaskDateTime').value = '';
  document.getElementById('scheduledTaskTimezone').value = task?.timezone || DEFAULT_TIMEZONE;
  document.getElementById('scheduledTaskExecutionMode').value = task?.mode || api.mode || 'cloud';
  document.getElementById('scheduledTaskMaxRetries').value = task?.max_retries ?? 1;
  document.getElementById('scheduledTaskTimeout').value = task?.timeout_seconds ?? 300;
  document.getElementById('scheduledTaskEnabled').checked = task?.enabled ?? true;
  document.getElementById('scheduledTaskAllowOverlap').checked = !!task?.allow_overlap;
  document.getElementById('scheduledTaskNotifyContact').value = notifications.contact_name || '';
  document.getElementById('scheduledTaskNotifyWebhook').value = notifications.webhook_name || '';
  document.getElementById('scheduledTaskEmailOnSuccess').checked = !!notifications.email_on_success;
  document.getElementById('scheduledTaskEmailOnFailure').checked = !!notifications.email_on_failure;
  document.getElementById('scheduledTaskAlertOnFailure').checked = notifications.alert_on_failure !== false;
  document.getElementById('scheduledTaskWebhookOnSuccess').checked = !!notifications.webhook_on_success;
  document.getElementById('scheduledTaskWebhookOnFailure').checked = !!notifications.webhook_on_failure;

  handleScheduledTaskTypeChange();
  try {
    await loadScheduledTaskWorkflows(true);
    renderScheduledTaskWorkflowOptions(selectedWorkflowId);
  } catch (error) {
    scheduledTaskWorkflows = [];
    scheduledTaskWorkflowsLoaded = false;
    renderScheduledTaskWorkflowOptions(selectedWorkflowId);
    showToast(`Could not load workflows: ${error.message}`, 'error');
  }
  showModal(modal);
}

function handleScheduledTaskTypeChange() {
  const type = document.getElementById('scheduledTaskType').value;
  const queryLabel = document.getElementById('scheduledTaskQueryLabel');
  const queryInput = document.getElementById('scheduledTaskQuery');
  document.getElementById('scheduledTaskQueryGroup').style.display = 'block';
  document.getElementById('scheduledTaskWorkflowGroup').style.display = type === 'workflow' ? 'block' : 'none';
  if (type === 'workflow') {
    queryLabel.textContent = 'Workflow Input';
    queryInput.placeholder = 'Optional URL, topic, host, or parameters for the workflow';
    updateScheduledTaskWorkflowDetails();
  } else {
    queryLabel.textContent = 'Query *';
    queryInput.placeholder = 'e.g., get bitcoin and solana price and email boss';
  }
}

function syncScheduledTaskWhenFromDateTime() {
  const dateTimeValue = document.getElementById('scheduledTaskDateTime')?.value;
  const scheduleInput = document.getElementById('scheduledTaskWhen');
  if (!dateTimeValue || !scheduleInput) return;

  const local = new Date(dateTimeValue);
  if (Number.isNaN(local.getTime())) return;

  const month = local.getMonth() + 1;
  const day = local.getDate();
  const year = local.getFullYear();
  let hour = local.getHours();
  const minute = String(local.getMinutes()).padStart(2, '0');
  const meridiem = hour >= 12 ? 'pm' : 'am';
  hour = hour % 12 || 12;
  scheduleInput.value = `${month}/${day}/${year} at ${hour}:${minute}${meridiem}`;
}

async function handleScheduledTaskSubmit(e) {
  e.preventDefault();

  const taskType = document.getElementById('scheduledTaskType').value;
  const notifications = {
    contact_name: document.getElementById('scheduledTaskNotifyContact').value.trim(),
    webhook_name: document.getElementById('scheduledTaskNotifyWebhook').value.trim(),
    email_on_success: document.getElementById('scheduledTaskEmailOnSuccess').checked,
    email_on_failure: document.getElementById('scheduledTaskEmailOnFailure').checked,
    alert_on_failure: document.getElementById('scheduledTaskAlertOnFailure').checked,
    webhook_on_success: document.getElementById('scheduledTaskWebhookOnSuccess').checked,
    webhook_on_failure: document.getElementById('scheduledTaskWebhookOnFailure').checked
  };
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
    allow_overlap: document.getElementById('scheduledTaskAllowOverlap').checked,
    metadata: {
      notifications
    }
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
  if (taskType === 'workflow') {
    const workflow = (scheduledTaskWorkflows || []).find(item => item.id === data.workflow_id);
    if (workflow?.requires_input && !data.query) {
      showToast('Workflow input is required for this workflow', 'error');
      return;
    }
  }
  if ((notifications.email_on_success || notifications.email_on_failure) && !notifications.contact_name) {
    showToast('Enter an email contact name when email notifications are enabled', 'error');
    return;
  }
  if ((notifications.webhook_on_success || notifications.webhook_on_failure) && !notifications.webhook_name) {
    showToast('Enter a named webhook when webhook notifications are enabled', 'error');
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
    const metadata = parseJsonSafe(task.metadata) || {};
    const notifications = metadata.notifications || {};

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
        <label class="form-label">Notifications</label>
        <div><strong>Email contact:</strong> ${escapeHtml(notifications.contact_name || 'none')}</div>
        <div><strong>Email on success:</strong> ${notifications.email_on_success ? '✅ Yes' : '❌ No'}</div>
        <div><strong>Email on failure:</strong> ${notifications.email_on_failure ? '✅ Yes' : '❌ No'}</div>
        <div><strong>Alert on failure:</strong> ${notifications.alert_on_failure ? '✅ Yes' : '❌ No'}</div>
        <div><strong>Webhook:</strong> ${escapeHtml(notifications.webhook_name || 'none')}</div>
        <div><strong>Webhook on success:</strong> ${notifications.webhook_on_success ? '✅ Yes' : '❌ No'}</div>
        <div><strong>Webhook on failure:</strong> ${notifications.webhook_on_failure ? '✅ Yes' : '❌ No'}</div>
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
                  ${renderScheduledRunNotifications(run)}
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

    showModal(modal);
  } catch (error) {
    showToast(`Error: ${error.message}`, 'error');
  }
}

function getScheduledRunNotificationLines(run) {
  const metadata = parseJsonSafe(run?.metadata) || {};
  const notifications = Array.isArray(metadata.notifications) ? metadata.notifications : [];
  if (!notifications.length) {
    return [];
  }

  return notifications.map(item => {
    const channel = item.channel || 'notification';
    const result = item.result || {};

    if (result.ok) {
      if (channel === 'email') {
        const toName = result.data?.to_name || result.data?.to || 'recipient';
        return `Email sent to ${toName}`;
      }
      if (channel === 'alert') {
        return 'Alert created';
      }
      if (channel === 'webhook') {
        const webhook = result.data?.webhook || result.data?.url || 'webhook';
        return `Webhook sent: ${webhook}`;
      }
      return `${channel} sent`;
    }

    if (result.error === 'cooldown_suppressed') {
      return `${channel} cooldown suppressed`;
    }

    return `${channel} failed: ${result.error || 'unknown error'}`;
  });
}

function renderScheduledRunNotifications(run) {
  const lines = getScheduledRunNotificationLines(run);
  if (!lines.length) {
    return '';
  }

  return `
    <div class="run-history-meta">
      Notifications: ${escapeHtml(lines.join(' • '))}
    </div>
  `;
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
        <div class="intel-form-label-row">
          <label class="form-label">Content</label>
          <div class="view-toggle" role="tablist" aria-label="Intel viewer preview mode">
            <button type="button" class="view-toggle-btn active" id="intelViewRawBtn" data-view="raw">Raw</button>
            <button type="button" class="view-toggle-btn" id="intelViewRenderedBtn" data-view="rendered">Rendered</button>
          </div>
        </div>
        <div class="code-block" id="intelViewRawContent" style="max-height: 400px; overflow-y: auto; white-space: pre-wrap;">${escapeHtml(file.content)}</div>
        <div class="markdown-viewer intel-rendered-preview" id="intelViewRenderedContent" style="display: none;">${renderMarkdown(file.content)}</div>
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
    bindIntelViewToggle();
    
    showModal(modal);
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
  
  showModal(modal);
}

// =========================================================================
// Modal Helpers
// =========================================================================

function closeAllModals() {
  document.querySelectorAll('.modal-overlay').forEach(m => m.classList.remove('active'));
  closeSidebar();
  setModalOpenState(false);
  editingMemory = null;
  editingFile = null;
  editingReminder = null;
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

function renderMarkdown(text) {
  const source = String(text || '');

  if (typeof marked === 'undefined' || !source.trim()) {
    return source.trim()
      ? `<pre class="code-block">${escapeHtml(source)}</pre>`
      : '<p style="color: var(--text-muted);">Nothing to preview yet.</p>';
  }

  try {
    const safeSource = escapeHtml(source);
    return marked.parse(safeSource, {
      gfm: true,
      breaks: false
    });
  } catch (error) {
    console.warn('Markdown render failed:', error);
    return `<pre class="code-block">${escapeHtml(source)}</pre>`;
  }
}

function updateIntelRenderedPreview() {
  const preview = document.getElementById('intelRenderedPreview');
  const textarea = document.getElementById('intelContent');
  if (!preview || !textarea) return;
  preview.innerHTML = renderMarkdown(textarea.value);
}

function setIntelEditorView(view) {
  intelEditorView = view === 'rendered' ? 'rendered' : 'raw';

  const textarea = document.getElementById('intelContent');
  const preview = document.getElementById('intelRenderedPreview');
  const rawBtn = document.getElementById('intelEditorRawBtn');
  const renderedBtn = document.getElementById('intelEditorRenderedBtn');

  if (!textarea || !preview || !rawBtn || !renderedBtn) return;

  const rendered = intelEditorView === 'rendered';
  textarea.style.display = rendered ? 'none' : '';
  preview.style.display = rendered ? 'block' : 'none';
  rawBtn.classList.toggle('active', !rendered);
  renderedBtn.classList.toggle('active', rendered);

  if (rendered) {
    updateIntelRenderedPreview();
  }
}

function bindIntelViewToggle() {
  const rawBtn = document.getElementById('intelViewRawBtn');
  const renderedBtn = document.getElementById('intelViewRenderedBtn');
  const rawContent = document.getElementById('intelViewRawContent');
  const renderedContent = document.getElementById('intelViewRenderedContent');

  if (!rawBtn || !renderedBtn || !rawContent || !renderedContent) return;

  const setView = (view) => {
    const rendered = view === 'rendered';
    rawBtn.classList.toggle('active', !rendered);
    renderedBtn.classList.toggle('active', rendered);
    rawContent.style.display = rendered ? 'none' : 'block';
    renderedContent.style.display = rendered ? 'block' : 'none';
  };

  rawBtn.addEventListener('click', () => setView('raw'));
  renderedBtn.addEventListener('click', () => setView('rendered'));
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

function reminderMatchesQuery(reminder, query) {
  const q = query.toLowerCase();
  const metadata = parseJsonSafe(reminder.metadata) || {};
  return [
    reminder.title,
    reminder.description,
    reminder.status,
    reminder.trigger_time,
    reminder.recurrence_rule,
    reminder.related_intel_file,
    reminder.callback_url,
    metadata?.gcal_event_id
  ].filter(Boolean).some(value => String(value).toLowerCase().includes(q));
}

function formatReminderStatus(status) {
  const normalized = String(status || '').toLowerCase();
  const labels = {
    scheduled: 'Scheduled',
    triggered: 'Triggered',
    acknowledged: 'Acknowledged',
    canceled: 'Canceled',
    expired: 'Expired'
  };
  return labels[normalized] || (normalized ? normalized.charAt(0).toUpperCase() + normalized.slice(1) : 'Unknown');
}

function getReminderStatusClass(status) {
  const normalized = String(status || '').toLowerCase();
  if (normalized === 'scheduled') return 'scheduled';
  if (normalized === 'triggered') return 'running';
  if (normalized === 'acknowledged') return 'success';
  if (normalized === 'canceled') return 'cancelled';
  if (normalized === 'expired') return 'failure';
  return 'neutral';
}

function getReminderTriggerTimestamp(triggerTime) {
  if (!triggerTime) return Number.NaN;
  const normalized = /(?:Z|[+-]\d{2}:\d{2})$/.test(String(triggerTime)) ? String(triggerTime) : `${triggerTime}Z`;
  return new Date(normalized).getTime();
}

function formatReminderTriggerLocal(triggerTime) {
  const ts = getReminderTriggerTimestamp(triggerTime);
  if (Number.isNaN(ts)) return String(triggerTime || 'Unknown');
  return new Date(ts).toLocaleString();
}

function formatReminderRelativeTime(triggerTime) {
  const ts = getReminderTriggerTimestamp(triggerTime);
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

function getReminderDueClass(reminder) {
  const status = String(reminder.status || '').toLowerCase();
  if (status !== 'scheduled' && status !== 'triggered') return '';

  const ts = getReminderTriggerTimestamp(reminder.trigger_time);
  if (Number.isNaN(ts)) return '';

  const diffMs = ts - Date.now();
  if (status === 'triggered' || diffMs < 0) return 'due-overdue';
  if (diffMs <= 15 * 60 * 1000) return 'due-urgent';
  if (diffMs <= 60 * 60 * 1000) return 'due-soon';
  return '';
}

function getReminderPreview(reminder) {
  if (reminder.description) return reminder.description;
  if (reminder.related_intel_file) return `Intel file: ${reminder.related_intel_file}`;
  if (reminder.callback_url) return `Callback: ${reminder.callback_url}`;
  if (reminder.recurrence_rule) return `Recurs: ${formatReminderRecurrence(reminder.recurrence_rule, reminder.trigger_time)}`;
  return `Reminder set for ${formatReminderTriggerLocal(reminder.trigger_time)}`;
}

function alertMatchesQuery(alert, query) {
  const q = query.toLowerCase();
  const metadata = parseJsonSafe(alert.metadata);
  return [
    alert.title,
    alert.description,
    alert.source,
    alert.status,
    alert.severity,
    alert.related_intel_file,
    typeof metadata === 'string' ? metadata : JSON.stringify(metadata || {})
  ].filter(Boolean).some(value => String(value).toLowerCase().includes(q));
}

function getAlertPreview(alert) {
  if (alert.description) return alert.description;
  if (alert.related_intel_file) return `Intel file: ${alert.related_intel_file}`;
  if (alert.auto_resolve_url) return `Auto-resolve URL: ${alert.auto_resolve_url}`;
  return `Alert from ${alert.source || 'unknown source'}`;
}

function formatAlertStatus(status) {
  const normalized = String(status || '').toLowerCase();
  if (!normalized) return 'Pending';
  const labels = {
    pending: 'Pending',
    acknowledged: 'Acknowledged',
    auto_resolved: 'Auto Resolved',
    canceled: 'Canceled'
  };
  return labels[normalized] || normalized.charAt(0).toUpperCase() + normalized.slice(1);
}

function formatAlertSeverity(severity) {
  const normalized = String(severity || '').toLowerCase();
  if (!normalized) return 'Medium';
  return normalized.charAt(0).toUpperCase() + normalized.slice(1);
}

function getAlertStatusClass(status) {
  const normalized = String(status || '').toLowerCase();
  if (normalized === 'pending') return 'running';
  if (normalized === 'acknowledged' || normalized === 'auto_resolved') return 'success';
  if (normalized === 'canceled') return 'cancelled';
  return 'neutral';
}

function parseReminderRecurrenceRule(rule, triggerTime = null) {
  const fallbackDate = triggerTime ? new Date(getReminderTriggerTimestamp(triggerTime)) : null;
  const fallbackJsDay = fallbackDate && !Number.isNaN(fallbackDate.getTime()) ? fallbackDate.getDay() : 1;
  const fallbackWeekday = (fallbackJsDay + 6) % 7;
  const fallbackDay = fallbackDate && !Number.isNaN(fallbackDate.getTime()) ? fallbackDate.getDate() : 1;
  const normalized = String(rule || '').trim().toUpperCase();

  if (!normalized) {
    return { type: 'once', weekday: fallbackWeekday, day: fallbackDay };
  }
  if (normalized === 'DAILY') {
    return { type: 'daily', weekday: fallbackWeekday, day: fallbackDay };
  }
  if (normalized.startsWith('WEEKLY:')) {
    const weekday = Number.parseInt(normalized.split(':')[1], 10);
    return { type: 'weekly', weekday: Number.isNaN(weekday) ? fallbackWeekday : weekday, day: fallbackDay };
  }
  if (normalized.startsWith('MONTHLY:')) {
    const day = Number.parseInt(normalized.split(':')[1], 10);
    return { type: 'monthly', weekday: fallbackWeekday, day: Number.isNaN(day) ? fallbackDay : day };
  }
  return { type: 'once', weekday: fallbackWeekday, day: fallbackDay };
}

function buildReminderRecurrenceRule() {
  const type = document.getElementById('reminderRecurrenceType').value;
  if (type === 'once') return null;
  if (type === 'daily') return 'DAILY';
  if (type === 'weekly') {
    const weekday = Number.parseInt(document.getElementById('reminderWeeklyDay').value, 10);
    return `WEEKLY:${Number.isNaN(weekday) ? 0 : weekday}`;
  }
  if (type === 'monthly') {
    const day = Number.parseInt(document.getElementById('reminderMonthlyDay').value, 10);
    return `MONTHLY:${Math.min(Math.max(Number.isNaN(day) ? 1 : day, 1), 31)}`;
  }
  return null;
}

function formatReminderRecurrence(rule, triggerTime = null) {
  const parsed = parseReminderRecurrenceRule(rule, triggerTime);
  const weekdayNames = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
  if (parsed.type === 'daily') return 'Every day';
  if (parsed.type === 'weekly') return `Every ${weekdayNames[parsed.weekday] || 'week'}`;
  if (parsed.type === 'monthly') return `Every month on day ${parsed.day}`;
  return 'Once';
}

function localDateTimeInputToUtcDb(value) {
  if (!value) return null;
  const local = new Date(value);
  if (Number.isNaN(local.getTime())) return null;
  return local.toISOString().replace('Z', '').slice(0, 19);
}

function formatReminderForDateTimeInput(triggerTime) {
  const ts = getReminderTriggerTimestamp(triggerTime);
  if (Number.isNaN(ts)) return '';
  const local = new Date(ts);
  const pad = (n) => String(n).padStart(2, '0');
  return `${local.getFullYear()}-${pad(local.getMonth() + 1)}-${pad(local.getDate())}T${pad(local.getHours())}:${pad(local.getMinutes())}`;
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
