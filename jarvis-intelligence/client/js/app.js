/**
 * Jarvis Intelligence Dashboard - Main Application
 */

// State
let currentTab = 'experiences';
let currentFilter = 'all';
let currentConfidenceFilter = null;
let currentExpSort = 'date';  // date, turns, tools
let currentExpToolFilter = null;  // null = all, specific tool name
let currentExpToolCountFilter = 'all';  // all, none, single, multi
let currentInsightSort = 'applied';  // applied, preferred, avoided, confidence, updated
let experiencesData = [];
let allExperiencesData = [];  // Keep unfiltered copy for tool list
let insightsData = [];
let allInsightsData = [];  // Keep unfiltered copy
let statsData = null;
let selectedExperienceId = null;
let selectedInsightId = null;

// ============================================================================
// Initialization
// ============================================================================

document.addEventListener('DOMContentLoaded', () => {
  setupEventListeners();
  loadInitialData();
});

function setupEventListeners() {
  // Mode selector
  document.getElementById('modeSelect').addEventListener('change', (e) => {
    api.setMode(e.target.value);
    loadInitialData();
  });
  
  // Navigation tabs (desktop and mobile)
  document.querySelectorAll('.nav-tab').forEach(tab => {
    tab.addEventListener('click', () => switchTab(tab.dataset.tab));
  });
  
  // Search
  document.getElementById('searchInput').addEventListener('input', debounce(handleSearch, 300));
  
  // Refresh button
  document.getElementById('refreshBtn').addEventListener('click', () => loadCurrentTab());
  
  // Filter items
  document.querySelectorAll('.filter-item[data-filter]').forEach(item => {
    item.addEventListener('click', () => handleFilterClick(item));
  });
  
  // Confidence filters
  document.querySelectorAll('.filter-item[data-confidence]').forEach(item => {
    item.addEventListener('click', () => handleConfidenceFilterClick(item));
  });
  
  // Experience sort selector
  document.getElementById('expSortSelect')?.addEventListener('change', (e) => {
    currentExpSort = e.target.value;
    experiencesData = sortExperiences(applyToolCountFilter([...allExperiencesData]));
    if (currentExpToolFilter) {
      experiencesData = experiencesData.filter(exp => {
        const tools = Array.isArray(exp.tools_used) ? exp.tools_used : [];
        return tools.includes(currentExpToolFilter);
      });
    }
    renderExperiences();
  });
  
  // Insight sort selector
  document.getElementById('insightSortSelect')?.addEventListener('change', (e) => {
    currentInsightSort = e.target.value;
    insightsData = sortInsights([...allInsightsData]);
    // Reapply confidence filter
    if (currentConfidenceFilter) {
      switch (currentConfidenceFilter) {
        case 'elite':
          insightsData = insightsData.filter(i => i.confidence >= 0.96);
          break;
        case 'high':
          insightsData = insightsData.filter(i => i.confidence >= 0.85 && i.confidence < 0.96);
          break;
        case 'good':
          insightsData = insightsData.filter(i => i.confidence >= 0.75 && i.confidence < 0.85);
          break;
        case 'medium':
          insightsData = insightsData.filter(i => i.confidence >= 0.50 && i.confidence < 0.75);
          break;
        case 'low':
          insightsData = insightsData.filter(i => i.confidence < 0.50);
          break;
      }
    }
    // Reapply constraint filter
    if (currentFilter !== 'all' && currentTab === 'insights') {
      insightsData = insightsData.filter(i => (i.constraint_type || 'positive') === currentFilter);
    }
    renderInsights();
  });
  
  // Experience tool filter
  document.getElementById('expToolFilter')?.addEventListener('change', (e) => {
    currentExpToolFilter = e.target.value || null;
    loadExperiences();
  });
  
  // Tool count filters
  document.querySelectorAll('.filter-item[data-toolcount]').forEach(item => {
    item.addEventListener('click', () => handleToolCountFilterClick(item));
  });
  
  // Health check button
  document.getElementById('runHealthCheckBtn').addEventListener('click', runHealthCheck);
  
  // Modal close buttons
  document.querySelectorAll('.modal-close').forEach(btn => {
    btn.addEventListener('click', closeAllModals);
  });
  
  // Click outside modal to close
  document.querySelectorAll('.modal-overlay').forEach(overlay => {
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) closeAllModals();
    });
  });
  
  // Experience modal actions
  document.getElementById('reembedExperienceBtn').addEventListener('click', reembedCurrentExperience);
  document.getElementById('deleteExperienceBtn').addEventListener('click', deleteCurrentExperience);
  
  // Insight modal actions
  document.getElementById('insightForm').addEventListener('submit', handleInsightSubmit);
  document.getElementById('reembedInsightBtn').addEventListener('click', reembedCurrentInsight);
  document.getElementById('deleteInsightBtn').addEventListener('click', deleteCurrentInsight);
  
  // Hamburger menu (mobile)
  document.getElementById('hamburgerBtn').addEventListener('click', toggleSidebar);
  document.getElementById('sidebarClose').addEventListener('click', closeSidebar);
  document.getElementById('sidebarOverlay').addEventListener('click', closeSidebar);
}

function handleToolCountFilterClick(item) {
  const toolCount = item.dataset.toolcount;
  
  // Update UI
  document.querySelectorAll('.filter-item[data-toolcount]').forEach(f => {
    f.classList.remove('active');
  });
  item.classList.add('active');
  
  currentExpToolCountFilter = toolCount;
  loadExperiences();
  closeSidebar();
}

// ============================================================================
// Data Loading
// ============================================================================

async function loadInitialData() {
  // Load all data to populate counts
  await Promise.all([
    loadAllExperiencesForCounts(),
    loadAllInsightsForCounts(),
    loadStats()
  ]);
  
  // Then load the current view
  loadCurrentTab();
}

async function loadAllExperiencesForCounts() {
  try {
    const result = await api.listExperiences({ limit: 1000 });
    const all = result.experiences || [];
    allExperiencesData = all;  // Store for tool filter dropdown
    
    const success = all.filter(e => e.outcome_success).length;
    const failed = all.filter(e => !e.outcome_success).length;
    
    // Tool count stats
    const noTools = all.filter(e => {
      const tools = Array.isArray(e.tools_used) ? e.tools_used : [];
      return tools.length === 0;
    }).length;
    const singleTool = all.filter(e => {
      const tools = Array.isArray(e.tools_used) ? e.tools_used : [];
      return tools.length === 1;
    }).length;
    const multiTool = all.filter(e => {
      const tools = Array.isArray(e.tools_used) ? e.tools_used : [];
      return tools.length > 1;
    }).length;
    
    document.getElementById('expAllCount').textContent = all.length;
    document.getElementById('expSuccessCount').textContent = success;
    document.getElementById('expFailedCount').textContent = failed;
    
    // Tool count stats
    const toolAllEl = document.getElementById('expToolAllCount');
    const toolNoneEl = document.getElementById('expToolNoneCount');
    const toolSingleEl = document.getElementById('expToolSingleCount');
    const toolMultiEl = document.getElementById('expToolMultiCount');
    
    if (toolAllEl) toolAllEl.textContent = all.length;
    if (toolNoneEl) toolNoneEl.textContent = noTools;
    if (toolSingleEl) toolSingleEl.textContent = singleTool;
    if (toolMultiEl) toolMultiEl.textContent = multiTool;
    
    // Update tool filter dropdown
    updateToolFilterDropdown();
  } catch (error) {
    console.error('Failed to load experience counts:', error);
  }
}

async function loadAllInsightsForCounts() {
  try {
    const result = await api.listInsights({ limit: 1000 });
    const all = result.insights || [];
    const positive = all.filter(i => (i.constraint_type || 'positive') === 'positive').length;
    const negative = all.filter(i => i.constraint_type === 'negative').length;
    
    // 5-tier confidence counts
    const eliteConf = all.filter(i => i.confidence >= 0.96).length;
    const highConf = all.filter(i => i.confidence >= 0.85 && i.confidence < 0.96).length;
    const goodConf = all.filter(i => i.confidence >= 0.75 && i.confidence < 0.85).length;
    const medConf = all.filter(i => i.confidence >= 0.50 && i.confidence < 0.75).length;
    const lowConf = all.filter(i => i.confidence < 0.50).length;
    
    document.getElementById('insightAllCount').textContent = all.length;
    document.getElementById('insightPositiveCount').textContent = positive;
    document.getElementById('insightNegativeCount').textContent = negative;
    document.getElementById('confEliteCount').textContent = eliteConf;
    document.getElementById('confHighCount').textContent = highConf;
    document.getElementById('confGoodCount').textContent = goodConf;
    document.getElementById('confMediumCount').textContent = medConf;
    document.getElementById('confLowCount').textContent = lowConf;
  } catch (error) {
    console.error('Failed to load insight counts:', error);
  }
}

async function loadCurrentTab() {
  switch (currentTab) {
    case 'experiences':
      await loadExperiences();
      break;
    case 'insights':
      await loadInsights();
      break;
    case 'reflection':
      await loadReflectionQueue();
      break;
    case 'stats':
      await loadStats();
      break;
  }
}

async function loadExperiences() {
  const container = document.getElementById('experiencesList');
  container.innerHTML = '<div class="loading"><div class="spinner"></div></div>';
  
  try {
    let successOnly = undefined;
    if (currentFilter === 'success') successOnly = true;
    else if (currentFilter === 'failed') successOnly = false;
    
    const result = await api.listExperiences({ limit: 500, success_only: successOnly });
    allExperiencesData = result.experiences || [];
    experiencesData = [...allExperiencesData];
    
    // Apply tool count filter
    experiencesData = applyToolCountFilter(experiencesData);
    
    // Apply specific tool filter
    if (currentExpToolFilter) {
      experiencesData = experiencesData.filter(exp => {
        const tools = Array.isArray(exp.tools_used) ? exp.tools_used : [];
        return tools.includes(currentExpToolFilter);
      });
    }
    
    // Apply sorting
    experiencesData = sortExperiences(experiencesData);
    
    renderExperiences();
    updateExperienceCounts();
    updateToolFilterDropdown();
  } catch (error) {
    showToast(`Failed to load experiences: ${error.message}`, 'error');
    container.innerHTML = '<div class="empty-state"><div class="empty-state-icon">❌</div><div class="empty-state-title">Failed to load</div></div>';
  }
}

function applyToolCountFilter(data) {
  switch (currentExpToolCountFilter) {
    case 'none':
      return data.filter(exp => {
        const tools = Array.isArray(exp.tools_used) ? exp.tools_used : [];
        return tools.length === 0;
      });
    case 'single':
      return data.filter(exp => {
        const tools = Array.isArray(exp.tools_used) ? exp.tools_used : [];
        return tools.length === 1;
      });
    case 'multi':
      return data.filter(exp => {
        const tools = Array.isArray(exp.tools_used) ? exp.tools_used : [];
        return tools.length > 1;
      });
    default:
      return data;
  }
}

function sortExperiences(data) {
  switch (currentExpSort) {
    case 'turns':
      return [...data].sort((a, b) => (b.turns_taken || 1) - (a.turns_taken || 1));
    case 'tools':
      return [...data].sort((a, b) => {
        const aTools = Array.isArray(a.tools_used) ? a.tools_used.length : 0;
        const bTools = Array.isArray(b.tools_used) ? b.tools_used.length : 0;
        return bTools - aTools;
      });
    case 'date':
    default:
      return [...data].sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));
  }
}

function updateToolFilterDropdown() {
  const select = document.getElementById('expToolFilter');
  if (!select) return;
  
  // Gather all unique tools from experiences
  const toolSet = new Set();
  allExperiencesData.forEach(exp => {
    const tools = Array.isArray(exp.tools_used) ? exp.tools_used : [];
    tools.forEach(t => toolSet.add(t));
  });
  
  const sortedTools = [...toolSet].sort();
  
  // Preserve selection
  const currentValue = select.value;
  
  select.innerHTML = '<option value="">All Tools</option>' +
    sortedTools.map(t => `<option value="${escapeHtml(t)}"${currentValue === t ? ' selected' : ''}>${escapeHtml(t)}</option>`).join('');
}

async function loadInsights() {
  const container = document.getElementById('insightsList');
  container.innerHTML = '<div class="loading"><div class="spinner"></div></div>';
  
  try {
    const options = { limit: 500 };  // Increased to get all insights for proper filtering
    if (currentFilter !== 'all' && currentTab === 'insights') {
      options.constraint_type = currentFilter;
    }
    
    const result = await api.listInsights(options);
    allInsightsData = result.insights || [];
    insightsData = [...allInsightsData];
    
    // Client-side filtering for 5-tier confidence
    if (currentConfidenceFilter) {
      switch (currentConfidenceFilter) {
        case 'elite':
          insightsData = insightsData.filter(i => i.confidence >= 0.96);
          break;
        case 'high':
          insightsData = insightsData.filter(i => i.confidence >= 0.85 && i.confidence < 0.96);
          break;
        case 'good':
          insightsData = insightsData.filter(i => i.confidence >= 0.75 && i.confidence < 0.85);
          break;
        case 'medium':
          insightsData = insightsData.filter(i => i.confidence >= 0.50 && i.confidence < 0.75);
          break;
        case 'low':
          insightsData = insightsData.filter(i => i.confidence < 0.50);
          break;
      }
    }
    
    // Apply sorting
    insightsData = sortInsights(insightsData);
    
    renderInsights();
    updateInsightCounts();
  } catch (error) {
    showToast(`Failed to load insights: ${error.message}`, 'error');
    container.innerHTML = '<div class="empty-state"><div class="empty-state-icon">❌</div><div class="empty-state-title">Failed to load</div></div>';
  }
}

function sortInsights(data) {
  switch (currentInsightSort) {
    case 'preferred':
      // Sort by those with preferred_tools first, then by how many
      return [...data].sort((a, b) => {
        const aHas = hasPreferredTools(a);
        const bHas = hasPreferredTools(b);
        if (aHas && !bHas) return -1;
        if (!aHas && bHas) return 1;
        // Both have or both don't - sort by count
        const aCount = getPreferredToolCount(a);
        const bCount = getPreferredToolCount(b);
        return bCount - aCount;
      });
    case 'avoided':
      // Sort by those with avoided_tools first, then by how many
      return [...data].sort((a, b) => {
        const aHas = hasAvoidedTools(a);
        const bHas = hasAvoidedTools(b);
        if (aHas && !bHas) return -1;
        if (!aHas && bHas) return 1;
        // Both have or both don't - sort by count
        const aCount = getAvoidedToolCount(a);
        const bCount = getAvoidedToolCount(b);
        return bCount - aCount;
      });
    case 'confidence':
      return [...data].sort((a, b) => (b.confidence || 0) - (a.confidence || 0));
    case 'updated':
      return [...data].sort((a, b) => new Date(b.updated_at || b.created_at) - new Date(a.updated_at || a.created_at));
    case 'helpful':
      return [...data].sort((a, b) => (b.times_helpful || 0) - (a.times_helpful || 0));
    case 'applied':
    default:
      return [...data].sort((a, b) => (b.times_applied || 0) - (a.times_applied || 0));
  }
}

// Helper functions for tool parsing
function hasPreferredTools(insight) {
  return parseToolsField(insight.preferred_tools).length > 0;
}

function hasAvoidedTools(insight) {
  return parseToolsField(insight.avoided_tools).length > 0;
}

function getPreferredToolCount(insight) {
  return parseToolsField(insight.preferred_tools).length;
}

function getAvoidedToolCount(insight) {
  return parseToolsField(insight.avoided_tools).length;
}

async function loadReflectionQueue() {
  const container = document.getElementById('reflectionContent');
  container.innerHTML = '<div class="loading"><div class="spinner"></div></div>';
  
  try {
    const [queueResult, metaResult] = await Promise.all([
      api.getReflectionQueue(50),
      api.getMetaKnowledge()
    ]);
    
    renderReflectionPanel(queueResult.queue || [], metaResult.entries || []);
  } catch (error) {
    showToast(`Failed to load reflection data: ${error.message}`, 'error');
  }
}

async function loadStats() {
  const container = document.getElementById('statsPanel');
  container.innerHTML = '<div class="loading"><div class="spinner"></div></div>';
  
  try {
    const [statsResult, perfResult] = await Promise.all([
      api.getStats(),
      api.getToolPerformance()
    ]);
    
    statsData = statsResult.stats;
    renderStats(statsData, perfResult.tools || []);
  } catch (error) {
    showToast(`Failed to load stats: ${error.message}`, 'error');
  }
}

// ============================================================================
// Rendering
// ============================================================================

function renderExperiences() {
  const container = document.getElementById('experiencesList');
  
  if (experiencesData.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <div class="empty-state-icon">📝</div>
        <div class="empty-state-title">No experiences found</div>
        <div class="empty-state-desc">Interactions will be recorded as Jarvis learns</div>
      </div>
    `;
    return;
  }
  
  container.innerHTML = `
    <div class="content-grid">
      ${experiencesData.map(exp => renderExperienceCard(exp)).join('')}
    </div>
  `;
  
  // Add click handlers
  container.querySelectorAll('.experience-card').forEach(card => {
    card.addEventListener('click', () => viewExperience(card.dataset.id));
  });
}

function renderExperienceCard(exp) {
  const tools = Array.isArray(exp.tools_used) ? exp.tools_used : [];
  const statusClass = exp.outcome_success ? 'success' : 'failed';
  const statusText = exp.outcome_success ? '✅ Success' : '❌ Failed';
  const hasEmbedding = exp.has_embedding ? '🔗' : '⚠️';
  const timestamp = formatDate(exp.timestamp);
  const turns = exp.turns_taken || 1;
  
  // Tool count badge
  let toolBadge = '';
  if (tools.length === 0) {
    toolBadge = '<span class="tool-count-badge none" title="No tools used">🚫 0</span>';
  } else if (tools.length === 1) {
    toolBadge = `<span class="tool-count-badge single" title="Single tool">1️⃣</span>`;
  } else {
    toolBadge = `<span class="tool-count-badge multi" title="${tools.length} tools used">🔢 ${tools.length}</span>`;
  }
  
  // Turns badge (highlight if many turns)
  const turnsBadge = turns > 3 
    ? `<span class="turns-badge high" title="${turns} turns - complex interaction">🔄 ${turns}</span>`
    : `<span class="turns-badge">🔄 ${turns}</span>`;
  
  return `
    <div class="card experience-card" data-id="${exp.id}">
      <div class="card-header">
        <div class="experience-query">${escapeHtml(truncate(exp.query, 150))}</div>
        <div class="experience-status">
          <span title="${exp.has_embedding ? 'Has embedding' : 'No embedding'}">${hasEmbedding}</span>
          <span class="status-badge ${statusClass}">${statusText}</span>
        </div>
      </div>
      ${tools.length > 0 ? `
        <div class="experience-tools">
          ${tools.slice(0, 5).map(t => `<span class="tool-tag">${escapeHtml(t)}</span>`).join('')}
          ${tools.length > 5 ? `<span class="tool-tag">+${tools.length - 5} more</span>` : ''}
        </div>
      ` : ''}
      <div class="card-footer">
        <div class="card-meta">
          <span>🕐 ${timestamp}</span>
          ${turnsBadge}
          ${toolBadge}
        </div>
        <div class="card-actions">
          <button class="btn btn-icon btn-small" title="View Details">👁️</button>
        </div>
      </div>
    </div>
  `;
}

function renderInsights() {
  const container = document.getElementById('insightsList');
  
  if (insightsData.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <div class="empty-state-icon">💡</div>
        <div class="empty-state-title">No insights found</div>
        <div class="empty-state-desc">Insights are generated from reflection on experiences</div>
      </div>
    `;
    return;
  }
  
  container.innerHTML = `
    <div class="content-grid">
      ${insightsData.map(insight => renderInsightCard(insight)).join('')}
    </div>
  `;
  
  // Add click handlers
  container.querySelectorAll('.insight-card').forEach(card => {
    card.addEventListener('click', () => viewInsight(card.dataset.id));
  });
}

function renderInsightCard(insight) {
  const constraint = insight.constraint_type || 'positive';
  const constraintLabel = constraint === 'positive' ? '✅ DO' : '❌ DON\'T';
  const confidence = insight.confidence || 0;
  const confTier = getConfidenceTier(confidence);
  const confLabel = getConfidenceLabel(confidence);
  const hasEmbedding = insight.has_embedding ? '🔗' : '⚠️';
  const createdDate = formatDate(insight.created_at);
  const updatedDate = insight.updated_at ? formatDate(insight.updated_at) : null;
  
  // Show updated date if different from created date, otherwise show created
  const displayDate = updatedDate && updatedDate !== createdDate 
    ? `Updated: ${updatedDate}` 
    : `Created: ${createdDate}`;
  
  // Parse preferred/avoided tools
  const preferredTools = parseToolsField(insight.preferred_tools);
  const avoidedTools = parseToolsField(insight.avoided_tools);
  
  return `
    <div class="card insight-card" data-id="${insight.id}">
      <div class="card-header">
        <div class="insight-description">${escapeHtml(truncate(insight.description, 200))}</div>
        <span class="constraint-badge ${constraint}">${constraintLabel}</span>
      </div>
      <div class="insight-timestamp" title="Created: ${createdDate}${updatedDate ? ', Updated: ' + updatedDate : ''}">
        📅 ${displayDate}
      </div>
      ${insight.applies_to_pattern ? `
        <div class="insight-pattern">📎 ${escapeHtml(truncate(insight.applies_to_pattern, 100))}</div>
      ` : ''}
      ${preferredTools.length > 0 || avoidedTools.length > 0 ? `
        <div class="insight-tools">
          ${preferredTools.length > 0 ? `
            <div class="tool-group preferred">
              <span class="tool-group-label">👍 Prefer:</span>
              ${preferredTools.slice(0, 3).map(t => `<span class="tool-tag preferred">${escapeHtml(t)}</span>`).join('')}
              ${preferredTools.length > 3 ? `<span class="tool-tag">+${preferredTools.length - 3}</span>` : ''}
            </div>
          ` : ''}
          ${avoidedTools.length > 0 ? `
            <div class="tool-group avoided">
              <span class="tool-group-label">👎 Avoid:</span>
              ${avoidedTools.slice(0, 3).map(t => `<span class="tool-tag avoided">${escapeHtml(t)}</span>`).join('')}
              ${avoidedTools.length > 3 ? `<span class="tool-tag">+${avoidedTools.length - 3}</span>` : ''}
            </div>
          ` : ''}
        </div>
      ` : ''}
      <div class="confidence-bar">
        <div class="confidence-fill ${constraint} ${confTier}" style="width: ${confidence * 100}%"></div>
      </div>
      <div class="card-footer">
        <div class="card-meta">
          <span title="${insight.has_embedding ? 'Has embedding' : 'No embedding'}">${hasEmbedding}</span>
          <span title="${confLabel}">📊 ${(confidence * 100).toFixed(0)}%</span>
          <span title="Times applied">🔄 ${insight.times_applied || 0}</span>
          <span title="Times helpful">✅ ${insight.times_helpful || 0}</span>
          <span title="Times failed">❌ ${insight.times_failed || 0}</span>
        </div>
        <div class="card-actions">
          <button class="btn btn-icon btn-small" title="Edit">✏️</button>
        </div>
      </div>
    </div>
  `;
}

// Parse tools field (can be JSON string, object with scores, or array of names)
function parseToolsField(field) {
  if (!field) return [];
  try {
    const parsed = typeof field === 'string' ? JSON.parse(field) : field;
    if (!parsed) return [];
    
    // If it's an array like ["tool1", "tool2"]
    if (Array.isArray(parsed)) {
      return parsed.filter(t => t && typeof t === 'string');
    }
    
    // If it's an object like {"tool1": 0.8, "tool2": 0.5}
    if (typeof parsed === 'object') {
      return Object.keys(parsed);
    }
    
    return [];
  } catch {
    return [];
  }
}

// Get confidence tier (5 tiers)
function getConfidenceTier(confidence) {
  const pct = confidence * 100;
  if (pct >= 96) return 'elite';
  if (pct >= 85) return 'high';
  if (pct >= 75) return 'good';
  if (pct >= 50) return 'medium';
  return 'low';
}

// Get human-readable confidence label
function getConfidenceLabel(confidence) {
  const pct = confidence * 100;
  if (pct >= 96) return `Elite (${pct.toFixed(0)}%) - Very high certainty`;
  if (pct >= 85) return `High (${pct.toFixed(0)}%) - Strong confidence`;
  if (pct >= 75) return `Good (${pct.toFixed(0)}%) - Reliable`;
  if (pct >= 50) return `Medium (${pct.toFixed(0)}%) - Moderate`;
  return `Low (${pct.toFixed(0)}%) - Weak`;
}

function renderReflectionPanel(queue, metaKnowledge) {
  const container = document.getElementById('reflectionContent');
  
  let html = `
    <div style="padding: var(--space-md);">
      <!-- Reflection Queue Section -->
      <div style="margin-bottom: var(--space-xl);">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: var(--space-md);">
          <h3 style="color: var(--text-primary);">🔄 Pending Reflections (${queue.length})</h3>
          <button class="btn btn-primary" id="triggerReflectionBtn">⚡ Process ${Math.min(5, queue.length)}</button>
        </div>
        ${queue.length === 0 ? `
          <div class="empty-state" style="padding: var(--space-lg);">
            <div class="empty-state-icon">✨</div>
            <div class="empty-state-title">Queue is empty</div>
            <div class="empty-state-desc">All experiences have been reflected upon</div>
          </div>
        ` : `
          <div class="queue-list">
            ${queue.slice(0, 10).map(item => `
              <div class="queue-item">
                <span class="queue-query">${escapeHtml(truncate(item.query || 'Unknown', 80))}</span>
                <span class="queue-priority">Priority: ${(item.priority || 0.5).toFixed(1)}</span>
              </div>
            `).join('')}
            ${queue.length > 10 ? `<div style="text-align: center; color: var(--text-muted); padding: var(--space-sm);">... and ${queue.length - 10} more</div>` : ''}
          </div>
        `}
      </div>
      
      <!-- Meta Knowledge Section -->
      <div>
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: var(--space-md);">
          <h3 style="color: var(--text-primary);">🧠 Meta-Knowledge (${metaKnowledge.length})</h3>
          <button class="btn btn-secondary" id="runMetaCognitionBtn">🔍 Run Analysis</button>
        </div>
        ${metaKnowledge.length === 0 ? `
          <div class="empty-state" style="padding: var(--space-lg);">
            <div class="empty-state-icon">🔍</div>
            <div class="empty-state-title">No meta-knowledge yet</div>
            <div class="empty-state-desc">Run meta-cognition to detect blind spots and patterns</div>
          </div>
        ` : `
          <div class="content-grid">
            ${metaKnowledge.map(mk => `
              <div class="card" style="cursor: default;">
                <div style="display: flex; justify-content: space-between; margin-bottom: var(--space-sm);">
                  <span style="font-weight: 600; color: var(--text-primary);">${getMetaTypeLabel(mk.meta_type)}</span>
                  <span style="font-size: var(--text-xs); color: var(--text-muted);">${formatDate(mk.timestamp)}</span>
                </div>
                <div style="font-size: var(--text-sm); color: var(--text-secondary); margin-bottom: var(--space-sm);">
                  ${escapeHtml(mk.description || mk.observation || '')}
                </div>
                ${mk.conclusion ? `
                  <div style="font-size: var(--text-xs); color: var(--text-muted); font-style: italic;">
                    → ${escapeHtml(mk.conclusion)}
                  </div>
                ` : ''}
              </div>
            `).join('')}
          </div>
        `}
      </div>
    </div>
  `;
  
  container.innerHTML = html;
  
  // Add event handlers
  const reflectBtn = document.getElementById('triggerReflectionBtn');
  if (reflectBtn) {
    reflectBtn.addEventListener('click', async () => {
      reflectBtn.disabled = true;
      reflectBtn.textContent = '⏳ Processing...';
      try {
        const result = await api.triggerReflection(5);
        showToast(`Processed ${result.processed} reflections`, 'success');
        await loadReflectionQueue();
        await loadInsights();
      } catch (error) {
        showToast(`Reflection failed: ${error.message}`, 'error');
      }
      reflectBtn.disabled = false;
      reflectBtn.textContent = `⚡ Process ${Math.min(5, queue.length)}`;
    });
  }
  
  const metaBtn = document.getElementById('runMetaCognitionBtn');
  if (metaBtn) {
    metaBtn.addEventListener('click', async () => {
      metaBtn.disabled = true;
      metaBtn.textContent = '⏳ Analyzing...';
      try {
        await api.runMetaCognition();
        showToast('Meta-cognition analysis complete', 'success');
        await loadReflectionQueue();
      } catch (error) {
        showToast(`Analysis failed: ${error.message}`, 'error');
      }
      metaBtn.disabled = false;
      metaBtn.textContent = '🔍 Run Analysis';
    });
  }
}

function renderStats(stats, toolPerformance) {
  const container = document.getElementById('statsPanel');
  
  const html = `
    <div class="content-list" style="overflow-y: auto; height: 100%;">
    <div class="stats-grid">
      <!-- Experience Stats -->
      <div class="stat-card">
        <div class="stat-value">${stats.experiences?.total || 0}</div>
        <div class="stat-label">Total Experiences</div>
        <div class="stat-trend up">+${stats.experiences?.recent_24h || 0} today</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">${stats.experiences?.success_rate || 0}%</div>
        <div class="stat-label">Success Rate</div>
      </div>
      
      <!-- Insight Stats -->
      <div class="stat-card">
        <div class="stat-value">${stats.insights?.total || 0}</div>
        <div class="stat-label">Total Insights</div>
        <div class="stat-trend up">+${stats.insights?.recent_24h || 0} today</div>
      </div>
      <div class="stat-card">
        <div class="stat-value" style="color: var(--success);">${stats.insights?.positive || 0}</div>
        <div class="stat-label">✅ Positive Constraints</div>
      </div>
      <div class="stat-card">
        <div class="stat-value" style="color: var(--error);">${stats.insights?.negative || 0}</div>
        <div class="stat-label">❌ Negative Constraints</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">${((stats.insights?.avg_confidence || 0) * 100).toFixed(0)}%</div>
        <div class="stat-label">Avg Confidence</div>
      </div>
      
      <!-- Application Stats -->
      <div class="stat-card">
        <div class="stat-value">${stats.application?.total_applied || 0}</div>
        <div class="stat-label">Times Applied</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">${stats.application?.helpfulness_rate || 0}%</div>
        <div class="stat-label">Helpfulness Rate</div>
      </div>
      
      <!-- Reflection -->
      <div class="stat-card">
        <div class="stat-value" style="color: ${stats.reflection?.pending > 10 ? 'var(--warning)' : 'var(--text-primary)'};">
          ${stats.reflection?.pending || 0}
        </div>
        <div class="stat-label">Pending Reflections</div>
      </div>
      
      <!-- Meta Knowledge -->
      <div class="stat-card">
        <div class="stat-value">${stats.meta_knowledge?.blind_spots || 0}</div>
        <div class="stat-label">⚠️ Blind Spots</div>
      </div>
      
      <!-- Database -->
      <div class="stat-card">
        <div class="stat-value">${stats.db_size_mb || 0} MB</div>
        <div class="stat-label">Database Size</div>
      </div>
    </div>
    
    <!-- Tool Performance Table -->
    ${toolPerformance.length > 0 ? `
      <div style="padding: 0 var(--space-lg) var(--space-lg);">
        <h3 style="color: var(--text-primary); margin-bottom: var(--space-md);">🛠️ Tool Performance (${toolPerformance.length} tools)</h3>
        <div style="background: var(--bg-card); border: 1px solid var(--border-primary); border-radius: var(--radius-lg); overflow: hidden; max-height: 400px; overflow-y: auto;">
          <table class="performance-table">
            <thead>
              <tr>
                <th>Tool</th>
                <th>Prefer</th>
                <th>Avoid</th>
                <th>Net Score</th>
              </tr>
            </thead>
            <tbody>
              ${toolPerformance.map(tool => `
                <tr>
                  <td><code>${escapeHtml(tool.name)}</code></td>
                  <td style="color: var(--success);">+${tool.prefer_count || 0}</td>
                  <td style="color: var(--error);">-${tool.avoid_count || 0}</td>
                  <td class="net-score ${tool.net_score >= 0 ? 'positive' : 'negative'}">
                    ${tool.net_score >= 0 ? '+' : ''}${tool.net_score}
                  </td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        </div>
      </div>
    ` : ''}
    
    <!-- Maintenance Actions -->
    <div style="padding: 0 var(--space-lg) var(--space-lg);">
      <h3 style="color: var(--text-primary); margin-bottom: var(--space-md);">🔧 Maintenance</h3>
      <div style="display: flex; gap: var(--space-sm); flex-wrap: wrap;">
        <button class="btn btn-secondary" id="runDecayBtn">📉 Run Decay</button>
        <button class="btn btn-secondary" id="runAnomalyBtn">🔍 Anomaly Detection</button>
        <button class="btn btn-primary" id="runAllMaintenanceBtn">🔧 Run All</button>
      </div>
    </div>
    </div><!-- close content-list wrapper -->
  `;
  
  container.innerHTML = html;
  
  // Add maintenance button handlers
  document.getElementById('runDecayBtn')?.addEventListener('click', async () => {
    showToast('Running decay job...', 'info');
    try {
      await api.runDecay();
      showToast('Decay job completed', 'success');
      await loadStats();
    } catch (e) {
      showToast(`Decay failed: ${e.message}`, 'error');
    }
  });
  
  document.getElementById('runAnomalyBtn')?.addEventListener('click', async () => {
    showToast('Running anomaly detection...', 'info');
    try {
      await api.runAnomalyDetection();
      showToast('Anomaly detection completed', 'success');
    } catch (e) {
      showToast(`Anomaly detection failed: ${e.message}`, 'error');
    }
  });
  
  document.getElementById('runAllMaintenanceBtn')?.addEventListener('click', async () => {
    showToast('Running all maintenance jobs...', 'info');
    try {
      await api.runAllMaintenance();
      showToast('All maintenance jobs completed', 'success');
      await loadStats();
    } catch (e) {
      showToast(`Maintenance failed: ${e.message}`, 'error');
    }
  });
}

// ============================================================================
// Modal Handlers
// ============================================================================

// Store current experience for copy functionality
let currentExperienceData = null;

async function viewExperience(id) {
  selectedExperienceId = id;
  const modal = document.getElementById('experienceModal');
  const body = document.getElementById('experienceModalBody');
  
  body.innerHTML = '<div class="loading"><div class="spinner"></div></div>';
  modal.classList.add('active');
  
  try {
    const result = await api.getExperience(id);
    const exp = result.experience;
    currentExperienceData = exp; // Store for copy functionality
    
    const tools = Array.isArray(exp.tools_used) ? exp.tools_used : [];
    const toolSequence = Array.isArray(exp.tool_sequence) ? exp.tool_sequence : [];
    
    body.innerHTML = `
      <div class="experience-detail-scroll">
        <div style="margin-bottom: var(--space-md);">
          <div class="form-label">Query</div>
          <div class="detail-block">
            ${escapeHtml(exp.query)}
          </div>
        </div>
        
        ${exp.context_summary ? `
          <div style="margin-bottom: var(--space-md);">
            <div class="form-label">Context Summary <span style="font-weight: normal; color: var(--text-muted);">(scroll to see all)</span></div>
            <div class="detail-block context-box">${escapeHtml(exp.context_summary)}</div>
          </div>
        ` : ''}
        
        <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: var(--space-md); margin-bottom: var(--space-md);">
          <div>
            <div class="form-label">Outcome</div>
            <span class="status-badge ${exp.outcome_success ? 'success' : 'failed'}">
              ${exp.outcome_success ? '✅ Success' : '❌ Failed'}
            </span>
          </div>
          <div>
            <div class="form-label">Turns</div>
            <span>${exp.turns_taken || 1}</span>
          </div>
          <div>
            <div class="form-label">Has Embedding</div>
            <span>${exp.has_embedding ? '✅ Yes' : '⚠️ No'}</span>
          </div>
          <div>
            <div class="form-label">Timestamp</div>
            <span>${formatDate(exp.timestamp)}</span>
          </div>
          <div>
            <div class="form-label">Experience ID</div>
            <span style="font-family: var(--font-mono);">${exp.id}</span>
          </div>
          <div>
            <div class="form-label">Error Occurred</div>
            <span>${exp.error_occurred ? '❌ Yes' : '✅ No'}</span>
          </div>
        </div>
        
        ${tools.length > 0 ? `
          <div style="margin-bottom: var(--space-md);">
            <div class="form-label">Tools Used (${tools.length})</div>
            <div style="display: flex; flex-wrap: wrap; gap: var(--space-xs);">
              ${tools.map(t => `<span class="tool-tag">${escapeHtml(t)}</span>`).join('')}
            </div>
          </div>
        ` : ''}
        
        ${toolSequence.length > 0 ? `
          <div style="margin-bottom: var(--space-md);">
            <div class="form-label">Tool Sequence (execution order)</div>
            <div class="detail-block" style="font-family: var(--font-mono); font-size: var(--text-xs);">
              ${toolSequence.map((t, i) => `${i + 1}. ${escapeHtml(t)}`).join('<br>')}
            </div>
          </div>
        ` : ''}
        
        ${exp.final_tool ? `
          <div style="margin-bottom: var(--space-md);">
            <div class="form-label">Final Tool</div>
            <span class="tool-tag">${escapeHtml(exp.final_tool)}</span>
          </div>
        ` : ''}
        
        ${exp.had_to_retry || exp.had_to_clarify ? `
          <div style="margin-bottom: var(--space-md);">
            <div class="form-label">Notes</div>
            <div class="detail-block">
              ${exp.had_to_retry ? '⚠️ Had to retry<br>' : ''}${exp.had_to_clarify ? '💬 Had to clarify' : ''}
            </div>
          </div>
        ` : ''}
      </div>
      
      <div style="margin-top: var(--space-md); padding-top: var(--space-md); border-top: 1px solid var(--border); display: flex; gap: var(--space-sm);">
        <button type="button" class="btn btn-small btn-secondary" onclick="copyExperienceJSON()">📋 Copy JSON</button>
        <button type="button" class="btn btn-small btn-secondary" onclick="copyContextSummary()">📄 Copy Context</button>
      </div>
    `;
  } catch (error) {
    body.innerHTML = `<div class="empty-state"><div class="empty-state-icon">❌</div><div class="empty-state-title">Failed to load</div><div class="empty-state-desc">${escapeHtml(error.message)}</div></div>`;
  }
}

// Copy to clipboard helper (works on HTTP and HTTPS)
function copyToClipboard(text) {
  // Try modern API first (HTTPS only)
  if (navigator.clipboard && window.isSecureContext) {
    return navigator.clipboard.writeText(text);
  }
  
  // Fallback for HTTP - use textarea trick
  return new Promise((resolve, reject) => {
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.style.position = 'fixed';
    textarea.style.left = '-9999px';
    textarea.style.top = '-9999px';
    document.body.appendChild(textarea);
    textarea.focus();
    textarea.select();
    
    try {
      const success = document.execCommand('copy');
      document.body.removeChild(textarea);
      if (success) {
        resolve();
      } else {
        reject(new Error('execCommand copy failed'));
      }
    } catch (err) {
      document.body.removeChild(textarea);
      reject(err);
    }
  });
}

// Make copy functions globally accessible
window.copyExperienceJSON = function() {
  if (!currentExperienceData) {
    showToast('No experience data loaded', 'error');
    return;
  }
  const json = JSON.stringify(currentExperienceData, null, 2);
  copyToClipboard(json).then(() => {
    showToast('Copied experience JSON to clipboard', 'success');
  }).catch(err => {
    showToast('Failed to copy: ' + err.message, 'error');
  });
};

window.copyContextSummary = function() {
  if (!currentExperienceData?.context_summary) {
    showToast('No context summary available', 'error');
    return;
  }
  copyToClipboard(currentExperienceData.context_summary).then(() => {
    showToast('Copied context summary to clipboard', 'success');
  }).catch(err => {
    showToast('Failed to copy: ' + err.message, 'error');
  });
};

async function viewInsight(id) {
  selectedInsightId = id;
  const modal = document.getElementById('insightModal');
  const body = document.getElementById('insightModalBody');
  
  modal.classList.add('active');
  
  try {
    const result = await api.getInsight(id);
    const insight = result.insight;
    
    document.getElementById('insightDescription').value = insight.description || '';
    document.getElementById('insightPattern').value = insight.applies_to_pattern || '';
    document.getElementById('insightConstraint').value = insight.constraint_type || 'positive';
    document.getElementById('insightConfidence').value = insight.confidence || 0.5;
    
    document.getElementById('insightDetails').innerHTML = `
      <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: var(--space-md); margin-top: var(--space-md); padding-top: var(--space-md); border-top: 1px solid var(--border-primary);">
        <div>
          <div class="form-label">Times Applied</div>
          <span>${insight.times_applied || 0}</span>
        </div>
        <div>
          <div class="form-label">Times Helpful</div>
          <span style="color: var(--success);">${insight.times_helpful || 0}</span>
        </div>
        <div>
          <div class="form-label">Times Failed</div>
          <span style="color: var(--error);">${insight.times_failed || 0}</span>
        </div>
        <div>
          <div class="form-label">Has Embedding</div>
          <span>${insight.has_embedding ? '✅ Yes' : '⚠️ No'}</span>
        </div>
        <div>
          <div class="form-label">Preferred Tools</div>
          <span>${insight.preferred_tools ? `<code>${escapeHtml(insight.preferred_tools)}</code>` : '-'}</span>
        </div>
        <div>
          <div class="form-label">Avoided Tools</div>
          <span>${insight.avoided_tools ? `<code>${escapeHtml(insight.avoided_tools)}</code>` : '-'}</span>
        </div>
      </div>
    `;
  } catch (error) {
    showToast(`Failed to load insight: ${error.message}`, 'error');
  }
}

async function handleInsightSubmit(e) {
  e.preventDefault();
  
  if (!selectedInsightId) return;
  
  const data = {
    description: document.getElementById('insightDescription').value,
    applies_to_pattern: document.getElementById('insightPattern').value,
    constraint_type: document.getElementById('insightConstraint').value,
    confidence: parseFloat(document.getElementById('insightConfidence').value)
  };
  
  try {
    await api.updateInsight(selectedInsightId, data);
    showToast('Insight updated successfully', 'success');
    
    // Prompt for re-embed
    if (confirm('Content changed. Re-embed the insight to update semantic matching?')) {
      await reembedCurrentInsight();
    }
    
    closeAllModals();
    await loadInsights();
  } catch (error) {
    showToast(`Failed to update insight: ${error.message}`, 'error');
  }
}

async function reembedCurrentExperience() {
  if (!selectedExperienceId) return;
  
  try {
    showToast('Re-embedding experience...', 'info');
    await api.reembedExperience(selectedExperienceId);
    showToast('Experience re-embedded successfully', 'success');
    await loadExperiences();
  } catch (error) {
    showToast(`Re-embed failed: ${error.message}`, 'error');
  }
}

async function deleteCurrentExperience() {
  if (!selectedExperienceId) return;
  
  if (!confirm('Are you sure you want to delete this experience?')) return;
  
  try {
    await api.deleteExperience(selectedExperienceId);
    showToast('Experience deleted', 'success');
    closeAllModals();
    await loadExperiences();
  } catch (error) {
    showToast(`Failed to delete: ${error.message}`, 'error');
  }
}

async function reembedCurrentInsight() {
  if (!selectedInsightId) return;
  
  try {
    showToast('Re-embedding insight...', 'info');
    await api.reembedInsight(selectedInsightId);
    showToast('Insight re-embedded successfully', 'success');
    await loadInsights();
  } catch (error) {
    showToast(`Re-embed failed: ${error.message}`, 'error');
  }
}

async function deleteCurrentInsight() {
  if (!selectedInsightId) return;
  
  if (!confirm('Are you sure you want to delete this insight?')) return;
  
  try {
    await api.deleteInsight(selectedInsightId);
    showToast('Insight deleted', 'success');
    closeAllModals();
    await loadInsights();
  } catch (error) {
    showToast(`Failed to delete: ${error.message}`, 'error');
  }
}

async function runHealthCheck() {
  const modal = document.getElementById('healthModal');
  const body = document.getElementById('healthModalBody');
  
  body.innerHTML = '<div class="loading"><div class="spinner"></div></div>';
  modal.classList.add('active');
  
  try {
    const result = await api.checkHealth();
    
    if (result.health) {
      body.innerHTML = `<pre style="white-space: pre-wrap; font-family: var(--font-mono); font-size: var(--text-sm);">${escapeHtml(JSON.stringify(result.health, null, 2))}</pre>`;
    } else if (result.output) {
      body.innerHTML = `<pre style="white-space: pre-wrap; font-family: var(--font-mono); font-size: var(--text-sm);">${escapeHtml(result.output)}</pre>`;
    } else {
      body.innerHTML = `<pre style="white-space: pre-wrap; font-family: var(--font-mono); font-size: var(--text-sm);">${escapeHtml(JSON.stringify(result, null, 2))}</pre>`;
    }
  } catch (error) {
    body.innerHTML = `<div class="empty-state"><div class="empty-state-icon">❌</div><div class="empty-state-title">Health check failed</div><div class="empty-state-desc">${escapeHtml(error.message)}</div></div>`;
  }
}

// ============================================================================
// Tab & Filter Management
// ============================================================================

function switchTab(tab) {
  currentTab = tab;
  currentFilter = 'all';
  currentConfidenceFilter = null;
  
  // Reset experience-specific filters when switching away
  if (tab !== 'experiences') {
    currentExpSort = 'date';
    currentExpToolFilter = null;
    currentExpToolCountFilter = 'all';
  }
  
  // Reset insight-specific filters when switching away
  if (tab !== 'insights') {
    currentInsightSort = 'applied';
  }
  
  // Update tab buttons (both desktop and mobile)
  document.querySelectorAll('.nav-tab').forEach(t => {
    t.classList.toggle('active', t.dataset.tab === tab);
  });
  
  // Update panels
  document.querySelectorAll('.tab-panel').forEach(p => {
    p.classList.remove('active');
  });
  document.getElementById(`${tab}Panel`)?.classList.add('active');
  
  // Update sidebar filters visibility
  document.getElementById('experienceFilters').style.display = tab === 'experiences' ? 'block' : 'none';
  document.getElementById('insightFilters').style.display = tab === 'insights' ? 'block' : 'none';
  
  // Show/hide experience sort selector
  const expSortContainer = document.getElementById('expSortContainer');
  if (expSortContainer) {
    expSortContainer.style.display = tab === 'experiences' ? 'flex' : 'none';
  }
  
  // Show/hide insight sort selector
  const insightSortContainer = document.getElementById('insightSortContainer');
  if (insightSortContainer) {
    insightSortContainer.style.display = tab === 'insights' ? 'flex' : 'none';
  }
  
  // Reset filter selections
  document.querySelectorAll('.filter-item').forEach(f => f.classList.remove('active'));
  document.querySelectorAll('.filter-item[data-filter="all"]').forEach(f => f.classList.add('active'));
  document.querySelectorAll('.filter-item[data-toolcount="all"]').forEach(f => f.classList.add('active'));
  
  // Reset sort selectors
  const expSortSelect = document.getElementById('expSortSelect');
  if (expSortSelect) expSortSelect.value = 'date';
  
  const insightSortSelect = document.getElementById('insightSortSelect');
  if (insightSortSelect) insightSortSelect.value = 'applied';
  
  // Reset tool filter
  const toolFilter = document.getElementById('expToolFilter');
  if (toolFilter) toolFilter.value = '';
  
  // Update search placeholder
  const searchInput = document.getElementById('searchInput');
  const placeholders = {
    experiences: 'Search experiences...',
    insights: 'Search insights...',
    reflection: 'Search reflection queue...',
    stats: 'Search...'
  };
  searchInput.placeholder = placeholders[tab] || 'Search...';
  
  // Load data
  loadCurrentTab();
  
  // Close sidebar on mobile
  closeSidebar();
}

function handleFilterClick(item) {
  const filter = item.dataset.filter;
  
  // Update UI
  item.closest('.filter-group').querySelectorAll('.filter-item').forEach(f => {
    f.classList.remove('active');
  });
  item.classList.add('active');
  
  currentFilter = filter;
  
  if (currentTab === 'experiences') {
    loadExperiences();
  } else if (currentTab === 'insights') {
    loadInsights();
  }
  
  closeSidebar();
}

function handleConfidenceFilterClick(item) {
  const confidence = item.dataset.confidence;
  
  // Toggle - clicking same one clears it
  if (currentConfidenceFilter === confidence) {
    currentConfidenceFilter = null;
    item.classList.remove('active');
  } else {
    document.querySelectorAll('.filter-item[data-confidence]').forEach(f => f.classList.remove('active'));
    item.classList.add('active');
    currentConfidenceFilter = confidence;
  }
  
  loadInsights();
  closeSidebar();
}

async function handleSearch(e) {
  const query = e.target.value.trim();
  
  if (!query) {
    loadCurrentTab();
    return;
  }
  
  if (currentTab === 'experiences') {
    try {
      const result = await api.searchExperiences(query);
      experiencesData = result.experiences || [];
      renderExperiences();
    } catch (error) {
      showToast(`Search failed: ${error.message}`, 'error');
    }
  } else if (currentTab === 'insights') {
    try {
      const result = await api.searchInsights(query);
      insightsData = result.insights || [];
      renderInsights();
    } catch (error) {
      showToast(`Search failed: ${error.message}`, 'error');
    }
  }
}

// ============================================================================
// Count Updates
// ============================================================================

function updateExperienceCounts() {
  // Use allExperiencesData for accurate total counts
  const source = allExperiencesData.length > 0 ? allExperiencesData : experiencesData;
  const all = source.length;
  const success = source.filter(e => e.outcome_success).length;
  const failed = source.filter(e => !e.outcome_success).length;
  
  // Tool count stats
  const noTools = source.filter(e => {
    const tools = Array.isArray(e.tools_used) ? e.tools_used : [];
    return tools.length === 0;
  }).length;
  const singleTool = source.filter(e => {
    const tools = Array.isArray(e.tools_used) ? e.tools_used : [];
    return tools.length === 1;
  }).length;
  const multiTool = source.filter(e => {
    const tools = Array.isArray(e.tools_used) ? e.tools_used : [];
    return tools.length > 1;
  }).length;
  
  document.getElementById('expAllCount').textContent = all;
  document.getElementById('expSuccessCount').textContent = success;
  document.getElementById('expFailedCount').textContent = failed;
  
  // Tool count stats
  const toolAllEl = document.getElementById('expToolAllCount');
  const toolNoneEl = document.getElementById('expToolNoneCount');
  const toolSingleEl = document.getElementById('expToolSingleCount');
  const toolMultiEl = document.getElementById('expToolMultiCount');
  
  if (toolAllEl) toolAllEl.textContent = all;
  if (toolNoneEl) toolNoneEl.textContent = noTools;
  if (toolSingleEl) toolSingleEl.textContent = singleTool;
  if (toolMultiEl) toolMultiEl.textContent = multiTool;
}

function updateInsightCounts() {
  const all = insightsData.length;
  const positive = insightsData.filter(i => (i.constraint_type || 'positive') === 'positive').length;
  const negative = insightsData.filter(i => i.constraint_type === 'negative').length;
  
  // 5-tier confidence counts
  const eliteConf = insightsData.filter(i => i.confidence >= 0.96).length;
  const highConf = insightsData.filter(i => i.confidence >= 0.85 && i.confidence < 0.96).length;
  const goodConf = insightsData.filter(i => i.confidence >= 0.75 && i.confidence < 0.85).length;
  const medConf = insightsData.filter(i => i.confidence >= 0.50 && i.confidence < 0.75).length;
  const lowConf = insightsData.filter(i => i.confidence < 0.50).length;
  
  document.getElementById('insightAllCount').textContent = all;
  document.getElementById('insightPositiveCount').textContent = positive;
  document.getElementById('insightNegativeCount').textContent = negative;
  document.getElementById('confEliteCount').textContent = eliteConf;
  document.getElementById('confHighCount').textContent = highConf;
  document.getElementById('confGoodCount').textContent = goodConf;
  document.getElementById('confMediumCount').textContent = medConf;
  document.getElementById('confLowCount').textContent = lowConf;
}

// ============================================================================
// Mobile Sidebar
// ============================================================================

function toggleSidebar() {
  const sidebar = document.getElementById('sidebar');
  const overlay = document.getElementById('sidebarOverlay');
  
  sidebar.classList.toggle('open');
  overlay.classList.toggle('active');
}

function closeSidebar() {
  const sidebar = document.getElementById('sidebar');
  const overlay = document.getElementById('sidebarOverlay');
  
  sidebar.classList.remove('open');
  overlay.classList.remove('active');
}

// ============================================================================
// Utilities
// ============================================================================

function closeAllModals() {
  document.querySelectorAll('.modal-overlay').forEach(m => m.classList.remove('active'));
  selectedExperienceId = null;
  selectedInsightId = null;
}

function showToast(message, type = 'info') {
  const container = document.getElementById('toastContainer');
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.textContent = message;
  container.appendChild(toast);
  
  setTimeout(() => {
    toast.remove();
  }, 4000);
}

function formatDate(dateStr) {
  if (!dateStr) return 'Unknown';
  const date = new Date(dateStr);
  return date.toLocaleDateString() + ' ' + date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function truncate(str, length) {
  if (!str) return '';
  return str.length > length ? str.substring(0, length) + '...' : str;
}

function escapeHtml(str) {
  if (!str) return '';
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

function debounce(func, wait) {
  let timeout;
  return function executedFunction(...args) {
    const later = () => {
      clearTimeout(timeout);
      func(...args);
    };
    clearTimeout(timeout);
    timeout = setTimeout(later, wait);
  };
}

function getMetaTypeLabel(type) {
  const labels = {
    'blind_spot': '⚠️ Blind Spot',
    'over_generalization': '🔄 Over-Generalization',
    'learning_quality': '📊 Learning Quality',
    'pattern_detected': '🔍 Pattern Detected'
  };
  return labels[type] || type;
}

