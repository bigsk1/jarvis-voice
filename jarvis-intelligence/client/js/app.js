/**
 * Jarvis Intelligence Dashboard - Main Application
 */

// State
let currentTab = 'experiences';
let currentFilter = 'all';
let currentConfidenceFilter = null;
let currentExpSort = 'date';  // date, turns, tools, completion_guard
let currentExpToolFilter = null;  // null = all, specific tool name
let currentExpToolCountFilter = 'all';  // all, none, single, multi
let currentExpCompletionGuardFilter = null;  // null = all, otherwise specific CG status
let currentInsightSort = 'updated';  // updated, applied, preferred, avoided, confidence, helpful
let currentFeedbackDays = 7;  // 7, 30, 90
let currentFeedbackRating = 'all';  // all, issues (1-3), good (4-5)
let experiencesData = [];
let allExperiencesData = [];  // Keep unfiltered copy for tool list
let insightsData = [];
let allInsightsData = [];  // Keep unfiltered copy
let feedbackData = [];
let allFeedbackData = [];
let statsData = null;
let selectedExperienceId = null;
let selectedInsightId = null;
let selectedFeedback = null;
const LIST_PAGE_SIZE = 50;
let experienceSummary = null;
let insightSummary = null;
let experiencePagination = { offset: 0, total: 0, hasMore: false, loading: false, observer: null };
let insightPagination = { offset: 0, total: 0, hasMore: false, loading: false, observer: null };

// ============================================================================
// Initialization
// ============================================================================

document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('app')?.classList.add('has-desktop-sidebar');
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
  document.getElementById('refreshBtn').addEventListener('click', () => refreshCurrentTab());
  
  // Filter items
  document.querySelectorAll('.filter-item[data-filter]').forEach(item => {
    item.addEventListener('click', () => handleFilterClick(item));
  });
  
  // Confidence filters
  document.querySelectorAll('.filter-item[data-confidence]').forEach(item => {
    item.addEventListener('click', () => handleConfidenceFilterClick(item));
  });
  
  // Feedback rating filters
  document.querySelectorAll('.filter-item[data-rating]').forEach(item => {
    item.addEventListener('click', () => {
      document.querySelectorAll('.filter-item[data-rating]').forEach(f => f.classList.remove('active'));
      item.classList.add('active');
      currentFeedbackRating = item.dataset.rating;
      loadFeedback();
    });
  });
  
  // Feedback days filters
  document.querySelectorAll('.filter-item[data-days]').forEach(item => {
    item.addEventListener('click', () => {
      document.querySelectorAll('.filter-item[data-days]').forEach(f => f.classList.remove('active'));
      item.classList.add('active');
      currentFeedbackDays = parseInt(item.dataset.days);
      loadFeedback();
    });
  });
  
  // Experience sort selector
  document.getElementById('expSortSelect')?.addEventListener('change', (e) => {
    currentExpSort = e.target.value;
    if (getCurrentSearchQuery()) {
      handleSearch({ target: document.getElementById('searchInput') });
    } else {
      loadExperiences();
    }
  });
  
  // Insight sort selector
  document.getElementById('insightSortSelect')?.addEventListener('change', (e) => {
    currentInsightSort = e.target.value;
    if (getCurrentSearchQuery()) {
      handleSearch({ target: document.getElementById('searchInput') });
    } else {
      loadInsights();
    }
  });
  
  // Experience tool filter
  document.getElementById('expToolFilter')?.addEventListener('change', (e) => {
    currentExpToolFilter = e.target.value || null;
    loadExperiences();
  });

  // Experience Completion Guard status filter
  document.getElementById('expCompletionGuardFilter')?.addEventListener('change', (e) => {
    currentExpCompletionGuardFilter = e.target.value || null;
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
    const result = await api.getExperienceSummary();
    experienceSummary = result.summary || {};
    updateExperienceCounts();
    updateToolFilterDropdown();
    updateCompletionGuardFilterDropdown();
  } catch (error) {
    console.error('Failed to load experience counts:', error);
  }
}

async function loadAllInsightsForCounts() {
  try {
    const result = await api.getInsightSummary();
    insightSummary = result.summary || {};
    updateInsightCounts();
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
    case 'feedback':
      await loadFeedback();
      break;
    case 'reflection':
      await loadReflectionQueue();
      break;
    case 'stats':
      await loadStats();
      break;
  }
}

async function refreshCurrentTab() {
  if (currentTab === 'experiences') {
    await loadAllExperiencesForCounts();
  } else if (currentTab === 'insights') {
    await loadAllInsightsForCounts();
  }
  await loadCurrentTab();
}

async function loadExperiences({ append = false } = {}) {
  const container = document.getElementById('experiencesList');
  if (experiencePagination.loading) return;

  if (!append) {
    disconnectPaginationObserver(experiencePagination);
    experiencePagination = { offset: 0, total: 0, hasMore: false, loading: false, observer: null };
    experiencesData = [];
    allExperiencesData = [];
    container.innerHTML = '<div class="loading"><div class="spinner"></div></div>';
  }

  experiencePagination.loading = true;
  
  try {
    let successOnly = undefined;
    if (currentFilter === 'success') successOnly = true;
    else if (currentFilter === 'failed') successOnly = false;
    
    const options = {
      limit: LIST_PAGE_SIZE,
      offset: experiencePagination.offset,
      success_only: successOnly,
      sort: currentExpSort,
    };
    if (currentExpToolCountFilter !== 'all') options.tool_count = currentExpToolCountFilter;
    if (currentExpToolFilter) options.tool = currentExpToolFilter;
    if (currentExpCompletionGuardFilter) options.completion_guard_status = currentExpCompletionGuardFilter;

    const result = await api.listExperiences(options);
    const nextExperiences = result.experiences || [];
    experiencesData = append ? [...experiencesData, ...nextExperiences] : nextExperiences;
    allExperiencesData = experiencesData;
    experiencePagination.offset = (result.offset || 0) + nextExperiences.length;
    experiencePagination.total = result.total || experiencesData.length;
    experiencePagination.hasMore = Boolean(result.has_more);
    
    renderExperiences();
    updateExperienceCounts();
    updateToolFilterDropdown();
    updateCompletionGuardFilterDropdown();
  } catch (error) {
    showToast(`Failed to load experiences: ${error.message}`, 'error');
    container.innerHTML = '<div class="empty-state"><div class="empty-state-icon">❌</div><div class="empty-state-title">Failed to load</div></div>';
  } finally {
    experiencePagination.loading = false;
    observeExperienceSentinel();
  }
}

function applyExperienceFilters(data) {
  let filtered = [...data];

  if (currentFilter === 'success') {
    filtered = filtered.filter(exp => exp.outcome_success);
  } else if (currentFilter === 'failed') {
    filtered = filtered.filter(exp => !exp.outcome_success);
  }

  filtered = applyToolCountFilter(filtered);

  if (currentExpToolFilter) {
    filtered = filtered.filter(exp => {
      const tools = Array.isArray(exp.tools_used) ? exp.tools_used : [];
      return tools.includes(currentExpToolFilter);
    });
  }

  if (currentExpCompletionGuardFilter) {
    filtered = filtered.filter(exp => getCompletionGuardStatus(exp) === currentExpCompletionGuardFilter);
  }

  return filtered;
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
    case 'completion_guard':
      return [...data].sort((a, b) => {
        const rankDelta = getCompletionGuardSortRank(a) - getCompletionGuardSortRank(b);
        if (rankDelta !== 0) return rankDelta;
        return parseStoredUtcDate(b.timestamp) - parseStoredUtcDate(a.timestamp);
      });
    case 'date':
    default:
      return [...data].sort((a, b) => parseStoredUtcDate(b.timestamp) - parseStoredUtcDate(a.timestamp));
  }
}

function updateToolFilterDropdown() {
  const select = document.getElementById('expToolFilter');
  if (!select) return;
  
  // Preserve selection
  const currentValue = select.value;
  const tools = Array.isArray(experienceSummary?.tools) ? experienceSummary.tools : [];
  
  select.innerHTML = '<option value="">All Tools</option>' +
    tools.map(tool => {
      const name = tool.name || tool.tool || '';
      const count = tool.count || 0;
      return `<option value="${escapeHtml(name)}"${currentValue === name ? ' selected' : ''}>${escapeHtml(name)} (${count})</option>`;
    }).join('');
}

function updateCompletionGuardFilterDropdown() {
  const select = document.getElementById('expCompletionGuardFilter');
  if (!select) return;

  const currentValue = select.value;
  const counts = experienceSummary?.completion_guard || {};
  const statuses = Object.keys(counts).sort((a, b) => getCompletionGuardStatusRank(a) - getCompletionGuardStatusRank(b));

  select.innerHTML = '<option value="">All CG Statuses</option>' +
    statuses.map(status => {
      const label = status === 'none' ? 'No Completion Guard' : getCompletionGuardStatusLabel(status);
      const count = counts[status] || 0;
      return `<option value="${escapeHtml(status)}"${currentValue === status ? ' selected' : ''}>${escapeHtml(label)} (${count})</option>`;
    }).join('');
}

async function loadInsights({ append = false } = {}) {
  const container = document.getElementById('insightsList');
  if (insightPagination.loading) return;

  if (!append) {
    disconnectPaginationObserver(insightPagination);
    insightPagination = { offset: 0, total: 0, hasMore: false, loading: false, observer: null };
    insightsData = [];
    allInsightsData = [];
    container.innerHTML = '<div class="loading"><div class="spinner"></div></div>';
  }

  insightPagination.loading = true;
  
  try {
    const options = {
      limit: LIST_PAGE_SIZE,
      offset: insightPagination.offset,
      sort: currentInsightSort,
    };
    if (currentFilter !== 'all' && currentTab === 'insights') {
      options.constraint_type = currentFilter;
    }
    if (currentConfidenceFilter) {
      options.confidence_tier = currentConfidenceFilter;
    }
    
    const result = await api.listInsights(options);
    const nextInsights = result.insights || [];
    insightsData = append ? [...insightsData, ...nextInsights] : nextInsights;
    allInsightsData = insightsData;
    insightPagination.offset = (result.offset || 0) + nextInsights.length;
    insightPagination.total = result.total || insightsData.length;
    insightPagination.hasMore = Boolean(result.has_more);
    
    renderInsights();
    updateInsightCounts();
  } catch (error) {
    showToast(`Failed to load insights: ${error.message}`, 'error');
    container.innerHTML = '<div class="empty-state"><div class="empty-state-icon">❌</div><div class="empty-state-title">Failed to load</div></div>';
  } finally {
    insightPagination.loading = false;
    observeInsightSentinel();
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
    case 'helpful':
      return [...data].sort((a, b) => (b.times_helpful || 0) - (a.times_helpful || 0));
    case 'applied':
      return [...data].sort((a, b) => (b.times_applied || 0) - (a.times_applied || 0));
    case 'updated':
    default:
      return [...data].sort((a, b) => parseStoredUtcDate(b.updated_at || b.created_at) - parseStoredUtcDate(a.updated_at || a.created_at));
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

// ============================================================================
// Feedback
// ============================================================================

async function loadFeedback() {
  const container = document.getElementById('feedbackList');
  container.innerHTML = '<div class="loading"><div class="spinner"></div></div>';
  
  try {
    // Build options based on filters
    const options = {
      days: currentFeedbackDays,
      limit: 200
    };
    
    if (currentFeedbackRating === 'issues') {
      options.rating_max = 3;
    } else if (currentFeedbackRating === 'good') {
      options.rating_min = 4;
    }
    
    const [feedbackResult, statsResult] = await Promise.all([
      api.listFeedback(options),
      api.getFeedbackStats(currentFeedbackDays)
    ]);
    
    allFeedbackData = feedbackResult.feedback || [];
    feedbackData = [...allFeedbackData];
    
    // Update stats display
    const stats = statsResult.stats || {};
    document.getElementById('fbAvgRating').textContent = stats.avg_rating?.toFixed(1) || '-';
    document.getElementById('fbTotalCount').textContent = stats.total || 0;
    
    const issueCount = (stats.by_rating?.[1] || 0) + (stats.by_rating?.[2] || 0) + (stats.by_rating?.[3] || 0);
    const issueRate = stats.total > 0 ? Math.round((issueCount / stats.total) * 100) : 0;
    document.getElementById('fbIssueRate').textContent = `${issueRate}%`;
    
    // Update filter counts
    const goodCount = (stats.by_rating?.[4] || 0) + (stats.by_rating?.[5] || 0);
    document.getElementById('fbAllCount').textContent = stats.total || 0;
    document.getElementById('fbIssuesCount').textContent = issueCount;
    document.getElementById('fbGoodCount').textContent = goodCount;
    
    renderFeedback();
  } catch (error) {
    container.innerHTML = `<div class="error">Failed to load feedback: ${error.message}</div>`;
  }
}

function renderFeedback() {
  const container = document.getElementById('feedbackList');
  
  if (feedbackData.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <span class="empty-icon">📊</span>
        <p>No feedback found for this period</p>
      </div>
    `;
    return;
  }
  
  container.innerHTML = feedbackData.map((fb, index) => {
    const rating = fb.rating || 0;
    const ratingStars = '★'.repeat(rating) + '☆'.repeat(5 - rating);
    const ratingClass = `rating-${rating}`;
    const tools = Array.isArray(fb.tools_used) ? fb.tools_used : [];
    const timestamp = fb.timestamp ? new Date(fb.timestamp).toLocaleString() : '';
    const query = fb.query || 'No query';
    const summary = fb.summary || 'No summary';
    
    return `
      <div class="feedback-card" data-index="${index}">
        <div class="feedback-card-header">
          <div class="feedback-rating ${ratingClass}">
            <span>${ratingStars}</span>
            <span>${rating}/5</span>
          </div>
          <span class="feedback-meta">${timestamp}</span>
        </div>
        <div class="feedback-query">${escapeHtml(query)}</div>
        <div class="feedback-summary">${escapeHtml(summary)}</div>
        ${tools.length > 0 ? `
          <div class="feedback-tools">
            ${tools.map(t => `<span class="feedback-tool-badge">${escapeHtml(t)}</span>`).join('')}
          </div>
        ` : ''}
        <div class="feedback-meta">
          <span>📍 ${fb.mode || 'unknown'}</span>
          ${fb.issues?.length > 0 ? `<span>⚠️ ${fb.issues.length} issue(s)</span>` : ''}
        </div>
      </div>
    `;
  }).join('');
  
  // Add click handlers
  container.querySelectorAll('.feedback-card').forEach(card => {
    card.addEventListener('click', () => {
      const index = parseInt(card.dataset.index);
      showFeedbackModal(feedbackData[index]);
    });
  });
}

function showFeedbackModal(feedback) {
  selectedFeedback = feedback;
  
  const modal = document.getElementById('feedbackModal');
  const body = document.getElementById('feedbackModalBody');
  
  const rating = feedback.rating || 0;
  const ratingStars = '★'.repeat(rating) + '☆'.repeat(5 - rating);
  const ratingClass = rating <= 3 ? 'rating-issues' : 'rating-good';
  
  let issuesHtml = '';
  if (feedback.issues && feedback.issues.length > 0) {
    issuesHtml = `
      <div class="feedback-detail-section">
        <h4>⚠️ Issues (${feedback.issues.length})</h4>
        ${feedback.issues.map(issue => `
          <div class="feedback-issue">
            <div class="feedback-issue-category">${escapeHtml(issue.category || 'other')}</div>
            <div class="feedback-issue-description">${escapeHtml(issue.description || '')}</div>
            ${issue.suggestion ? `<div class="feedback-issue-suggestion">💡 ${escapeHtml(issue.suggestion)}</div>` : ''}
          </div>
        `).join('')}
      </div>
    `;
  }
  
  let toolRatingsHtml = '';
  if (feedback.tool_ratings && Object.keys(feedback.tool_ratings).length > 0) {
    toolRatingsHtml = `
      <div class="feedback-detail-section">
        <h4>🛠️ Tool Ratings</h4>
        ${Object.entries(feedback.tool_ratings).map(([tool, data]) => `
          <div class="feedback-tool-rating">
            <strong>${escapeHtml(tool)}</strong>: ${data.rating}/5
            ${data.note ? ` - ${escapeHtml(data.note)}` : ''}
          </div>
        `).join('')}
      </div>
    `;
  }
  
  body.innerHTML = `
    <div class="feedback-detail-section">
      <h4>📝 Query</h4>
      <div class="feedback-query" style="white-space: normal;">${escapeHtml(feedback.query || 'N/A')}</div>
    </div>
    
    <div class="feedback-detail-section">
      <h4>📊 Rating</h4>
      <div class="feedback-rating ${ratingClass}" style="font-size: 1.5rem;">
        ${ratingStars} (${rating}/5)
      </div>
    </div>
    
    <div class="feedback-detail-section">
      <h4>📋 Summary</h4>
      <p>${escapeHtml(feedback.summary || 'No summary')}</p>
    </div>
    
    ${feedback.positive ? `
      <div class="feedback-detail-section">
        <h4>✅ Positive</h4>
        <div class="feedback-positive">${escapeHtml(feedback.positive)}</div>
      </div>
    ` : ''}
    
    ${issuesHtml}
    ${toolRatingsHtml}
    
    <div class="feedback-detail-section">
      <h4>💬 Response</h4>
      <div class="feedback-response-preview">${escapeHtml(feedback.final_speech || feedback.raw_llm_response || 'N/A')}</div>
    </div>
    
    <div class="feedback-detail-section">
      <h4>ℹ️ Metadata</h4>
      <div class="feedback-meta" style="flex-direction: column; gap: var(--space-xs);">
        <span>🕐 ${feedback.timestamp ? new Date(feedback.timestamp).toLocaleString() : 'N/A'}</span>
        <span>📍 Mode: ${feedback.mode || 'unknown'}</span>
        <span>🤖 Feedback by: ${feedback.feedback_model || 'unknown'}</span>
        <span>🔑 Session: ${feedback.session_id || 'N/A'}</span>
      </div>
    </div>
  `;
  
  showModal(modal);
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
    ${renderPaginationFooter('experience', experiencesData.length, experiencePagination)}
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
  const timestamp = formatRecordTimestamp(exp, 'timestamp');
  const timestampTitle = formatRecordTimestampTitle(exp, 'timestamp');
  const turns = exp.turns_taken || 1;
  const completionGuardBadge = renderCompletionGuardBadge(exp.completion_guard);
  
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
          <span title="${escapeHtml(timestampTitle)}">🕐 ${timestamp}</span>
          ${turnsBadge}
          ${toolBadge}
          ${completionGuardBadge}
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
    ${renderPaginationFooter('insight', insightsData.length, insightPagination)}
  `;
  
  // Add click handlers
  container.querySelectorAll('.insight-card').forEach(card => {
    card.addEventListener('click', () => viewInsight(card.dataset.id));
  });
}

function renderPaginationFooter(kind, loadedCount, pagination) {
  if (pagination.hasMore) {
    return `
      <div class="infinite-scroll-sentinel" id="${kind}ScrollSentinel">
        <div class="spinner spinner-small"></div>
      </div>
    `;
  }

  if (loadedCount > 0) {
    const total = pagination.total || loadedCount;
    return `<div class="list-end-note">Showing ${loadedCount} of ${total}</div>`;
  }

  return '';
}

function disconnectPaginationObserver(pagination) {
  if (pagination?.observer) {
    pagination.observer.disconnect();
    pagination.observer = null;
  }
}

function observeExperienceSentinel() {
  disconnectPaginationObserver(experiencePagination);
  if (!experiencePagination.hasMore || experiencePagination.loading || currentTab !== 'experiences' || getCurrentSearchQuery()) return;

  const root = document.getElementById('experiencesList');
  const sentinel = document.getElementById('experienceScrollSentinel');
  if (!root || !sentinel) return;

  experiencePagination.observer = new IntersectionObserver((entries) => {
    if (entries.some(entry => entry.isIntersecting)) {
      loadExperiences({ append: true });
    }
  }, { root, rootMargin: '300px 0px', threshold: 0.01 });
  experiencePagination.observer.observe(sentinel);
}

function observeInsightSentinel() {
  disconnectPaginationObserver(insightPagination);
  if (!insightPagination.hasMore || insightPagination.loading || currentTab !== 'insights' || getCurrentSearchQuery()) return;

  const root = document.getElementById('insightsList');
  const sentinel = document.getElementById('insightScrollSentinel');
  if (!root || !sentinel) return;

  insightPagination.observer = new IntersectionObserver((entries) => {
    if (entries.some(entry => entry.isIntersecting)) {
      loadInsights({ append: true });
    }
  }, { root, rootMargin: '300px 0px', threshold: 0.01 });
  insightPagination.observer.observe(sentinel);
}

function renderInsightCard(insight) {
  const constraint = insight.constraint_type || 'positive';
  const constraintLabel = constraint === 'positive' ? '✅ DO' : '❌ DON\'T';
  const confidence = insight.confidence || 0;
  const confTier = getConfidenceTier(confidence);
  const confLabel = getConfidenceLabel(confidence);
  const hasEmbedding = insight.has_embedding ? '🔗' : '⚠️';
  const createdDate = formatRecordTimestamp(insight, 'created_at');
  const updatedDate = insight.updated_at ? formatRecordTimestamp(insight, 'updated_at') : null;
  const timestampTitle = [
    `Created: ${formatRecordTimestampTitle(insight, 'created_at')}`,
    updatedDate ? `Updated: ${formatRecordTimestampTitle(insight, 'updated_at')}` : null
  ].filter(Boolean).join('\n');
  const reflectionUsage = formatReflectionUsage(insight, true);
  
  // Show updated date if different from created date, otherwise show created
  const displayDate = updatedDate && updatedDate !== createdDate 
    ? `Updated: ${updatedDate}` 
    : `Created: ${createdDate}`;
  
  // Parse preferred/avoided tools
  const preferredTools = parseToolsField(insight.preferred_tools);
  const avoidedTools = parseToolsField(insight.avoided_tools);
  const preferredSequence = parseToolsField(insight.preferred_tool_sequence);
  
  return `
    <div class="card insight-card" data-id="${insight.id}">
      <div class="card-header">
        <div class="insight-description">${escapeHtml(truncate(insight.description, 200))}</div>
        <span class="constraint-badge ${constraint}">${constraintLabel}</span>
      </div>
      <div class="insight-timestamp" title="${escapeHtml(timestampTitle)}">
        📅 ${displayDate}
      </div>
      ${insight.applies_to_pattern ? `
        <div class="insight-pattern">📎 ${escapeHtml(truncate(insight.applies_to_pattern, 100))}</div>
      ` : ''}
      ${preferredTools.length > 0 || avoidedTools.length > 0 || preferredSequence.length > 0 ? `
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
          ${preferredSequence.length > 0 ? `
            <div class="tool-group">
              <span class="tool-group-label">Sequence:</span>
              <span class="tool-tag">${escapeHtml(preferredSequence.join(' → '))}</span>
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
          ${reflectionUsage ? `<span title="Lifetime reflection cost across all updates: ${escapeHtml(formatReflectionUsage(insight))} · Last run: ${escapeHtml(formatReflectionProvider(insight))}">🧾 ${escapeHtml(reflectionUsage)}</span>` : ''}
        </div>
        <div class="card-actions">
          <button class="btn btn-icon btn-small" title="Edit">✏️</button>
        </div>
      </div>
    </div>
  `;
}

function getReflectionTotalTokens(insight) {
  return Number(insight?.reflection_total_tokens || 0);
}

function formatReflectionCost(cost) {
  const numeric = Number(cost || 0);
  if (!Number.isFinite(numeric) || numeric <= 0) return '$0';
  return numeric < 0.01 ? `$${numeric.toFixed(4)}` : `$${numeric.toFixed(2)}`;
}

function formatReflectionUsage(insight, compact = false) {
  const totalTokens = getReflectionTotalTokens(insight);
  if (!totalTokens) return '';
  const tokenText = `${totalTokens.toLocaleString()} ${compact ? 'tok' : 'tokens'}`;
  const costText = formatReflectionCost(insight.reflection_cost_usd);
  return compact ? `${tokenText} ${costText}` : `${tokenText} (${costText})`;
}

function formatReflectionProvider(insight) {
  const provider = insight?.reflection_provider || 'unknown';
  const model = insight?.reflection_model || 'unknown';
  return `${provider} / ${model}`;
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

function renderToolSequenceField(field) {
  const tools = parseToolsField(field);
  return tools.length > 0 ? escapeHtml(tools.join(' → ')) : '-';
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
          <div style="display: flex; gap: var(--space-sm);">
            ${queue.length > 0 ? `<button class="btn btn-secondary" id="clearAllReflectionsBtn" title="Cancel all pending reflections">🗑️ Clear All</button>` : ''}
            <button class="btn btn-primary" id="triggerReflectionBtn">⚡ Process ${Math.min(5, queue.length)}</button>
          </div>
        </div>
        ${queue.length === 0 ? `
          <div class="empty-state" style="padding: var(--space-lg);">
            <div class="empty-state-icon">✨</div>
            <div class="empty-state-title">Queue is empty</div>
            <div class="empty-state-desc">All experiences have been reflected upon</div>
          </div>
        ` : `
          <div class="queue-list">
            ${queue.slice(0, 20).map(item => `
              <div class="queue-item" style="display: flex; align-items: center; gap: var(--space-sm);">
                <button class="btn btn-icon delete-reflection-btn" data-id="${item.id}" title="Cancel this reflection (don't process)">✕</button>
                <div style="flex: 1; min-width: 0;">
                  <span class="queue-query">${escapeHtml(item.query || 'Unknown')}</span>
                  <span class="queue-meta" style="font-size: var(--text-xs); color: var(--text-muted); margin-left: var(--space-sm);">
                    ${item.outcome_success ? '✅' : '❌'} Exp #${item.experience_id}
                  </span>
                </div>
                <span class="queue-priority">P: ${(item.priority || 0.5).toFixed(1)}</span>
              </div>
            `).join('')}
            ${queue.length > 20 ? `<div style="text-align: center; color: var(--text-muted); padding: var(--space-sm);">... and ${queue.length - 20} more</div>` : ''}
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
  
  // Delete individual reflection buttons
  document.querySelectorAll('.delete-reflection-btn').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const id = btn.dataset.id;
      if (!confirm('Cancel this reflection? It won\'t be processed for insights.')) return;
      
      btn.disabled = true;
      btn.textContent = '⏳';
      try {
        await api.deleteReflection(id);
        showToast('Reflection cancelled', 'success');
        await loadReflectionQueue();
      } catch (error) {
        showToast(`Failed to cancel: ${error.message}`, 'error');
        btn.disabled = false;
        btn.textContent = '✕';
      }
    });
  });
  
  // Clear all reflections button
  const clearAllBtn = document.getElementById('clearAllReflectionsBtn');
  if (clearAllBtn) {
    clearAllBtn.addEventListener('click', async () => {
      if (!confirm('Cancel ALL pending reflections? This cannot be undone.')) return;
      
      clearAllBtn.disabled = true;
      clearAllBtn.textContent = '⏳ Clearing...';
      try {
        const result = await api.deleteAllReflections();
        showToast(`Cancelled ${result.deleted} reflections`, 'success');
        await loadReflectionQueue();
      } catch (error) {
        showToast(`Failed to clear: ${error.message}`, 'error');
        clearAllBtn.disabled = false;
        clearAllBtn.textContent = '🗑️ Clear All';
      }
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

      ${renderCompletionGuardStats(stats.completion_guard)}
    </div>
    
    <!-- Tool Performance Table -->
    ${toolPerformance.length > 0 ? `
      <div style="padding: 0 var(--space-lg) var(--space-lg);">
        <h3 style="color: var(--text-primary); margin-bottom: var(--space-md);">🛠️ Tool Performance (${toolPerformance.length} tools)</h3>
        <div class="performance-table-wrapper">
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
    // Show modal immediately with loading state
    const modal = document.getElementById('anomalyModal');
    const body = document.getElementById('anomalyModalBody');
    body.innerHTML = '<div class="loading"><div class="spinner"></div></div>';
    showModal(modal);
    
    try {
      const result = await api.runAnomalyDetection();
      showAnomalyResults(result);
      showToast('Anomaly detection completed', 'success');
    } catch (e) {
      body.innerHTML = `<div class="error-message">❌ ${e.message}</div>`;
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

function renderCompletionGuardStats(completionGuardStats) {
  const total = completionGuardStats?.total || 0;
  if (!total) return '';

  const byStatus = completionGuardStats.by_status || {};
  const statusRows = Object.entries(byStatus)
    .sort(([a], [b]) => getCompletionGuardStatusRank(a) - getCompletionGuardStatusRank(b))
    .map(([status, count]) => `
      <div class="stat-breakdown-row">
        <span>${escapeHtml(getCompletionGuardStatusLabel(status))}</span>
        <strong>${count}</strong>
      </div>
    `).join('');

  return `
    <div class="stat-card stat-card-wide">
      <div class="stat-value" style="color: var(--warning);">${completionGuardStats.repaired || 0}</div>
      <div class="stat-label">Completion Guard Repairs</div>
      <div class="stat-trend">Lifetime CG total: ${total}</div>
      <div class="stat-breakdown">
        ${statusRows}
      </div>
    </div>
  `;
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
  showModal(modal);
  
  try {
    const result = await api.getExperience(id);
    const exp = result.experience;
    currentExperienceData = exp; // Store for copy functionality
    
    const tools = Array.isArray(exp.tools_used) ? exp.tools_used : [];
    const toolSequence = Array.isArray(exp.tool_sequence) ? exp.tool_sequence : [];
    const completionGuard = exp.completion_guard || exp.raw_data?.completion_guard;
    const rawData = exp.raw_data;
    
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
            ${renderTimestampStack(exp, 'timestamp')}
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

        ${completionGuard ? `
          <div style="margin-bottom: var(--space-md);">
            <div class="form-label">Completion Guard</div>
            ${renderCompletionGuardSummary(completionGuard)}
            ${renderJsonDetailBlock(completionGuard, 'completion-guard-json')}
          </div>
        ` : ''}

        ${rawData ? `
          <div style="margin-bottom: var(--space-md);">
            <div class="form-label">Raw Stored Data</div>
            ${renderJsonDetailBlock(rawData, 'raw-data-json')}
          </div>
        ` : ''}
      </div>
      
      <div style="margin-top: var(--space-md); padding-top: var(--space-md); border-top: 1px solid var(--border); display: flex; gap: var(--space-sm);">
        <button type="button" class="btn btn-small btn-secondary" onclick="copyExperienceJSON()">📋 Copy JSON</button>
        <button type="button" class="btn btn-small btn-secondary" onclick="copyContextSummary()">📄 Copy Context</button>
        <button type="button" class="btn btn-small btn-secondary" onclick="copyRawExperienceData()">🧾 Copy Raw</button>
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

window.copyRawExperienceData = function() {
  if (!currentExperienceData?.raw_data) {
    showToast('No raw data available', 'error');
    return;
  }
  copyToClipboard(JSON.stringify(currentExperienceData.raw_data, null, 2)).then(() => {
    showToast('Copied raw experience data to clipboard', 'success');
  }).catch(err => {
    showToast('Failed to copy: ' + err.message, 'error');
  });
};

async function viewInsight(id) {
  selectedInsightId = id;
  const modal = document.getElementById('insightModal');
  const body = document.getElementById('insightModalBody');
  
  showModal(modal);
  
  try {
    const result = await api.getInsight(id);
    const insight = result.insight;
    const evidence = Array.isArray(insight.evidence) ? insight.evidence : [];
    
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
          <div class="form-label">Created</div>
          ${renderTimestampStack(insight, 'created_at')}
        </div>
        <div>
          <div class="form-label">Updated</div>
          ${renderTimestampStack(insight, 'updated_at')}
        </div>
        ${insight.last_applied ? `
          <div>
            <div class="form-label">Last Applied</div>
            ${renderTimestampStack(insight, 'last_applied')}
          </div>
        ` : ''}
        ${getReflectionTotalTokens(insight) > 0 ? `
          <div>
            <div class="form-label" title="Cumulative across every reflection that created or updated this insight">Lifetime Reflection Cost</div>
            <span>${escapeHtml(formatReflectionUsage(insight))}</span>
          </div>
          <div>
            <div class="form-label" title="Provider/model from the most recent reflection update (earlier updates may have used different models)">Last Reflection Provider</div>
            <span>${escapeHtml(formatReflectionProvider(insight))}</span>
          </div>
          <div>
            <div class="form-label" title="Cumulative input/output tokens across all reflections on this insight">Lifetime Reflection Tokens</div>
            <span title="Input: ${Number(insight.reflection_input_tokens || 0).toLocaleString()} | Output: ${Number(insight.reflection_output_tokens || 0).toLocaleString()}">
              ${Number(insight.reflection_input_tokens || 0).toLocaleString()} in / ${Number(insight.reflection_output_tokens || 0).toLocaleString()} out
            </span>
          </div>
        ` : ''}
        <div>
          <div class="form-label">Preferred Tools</div>
          <span>${insight.preferred_tools ? `<code>${escapeHtml(insight.preferred_tools)}</code>` : '-'}</span>
        </div>
        <div>
          <div class="form-label">Avoided Tools</div>
          <span>${insight.avoided_tools ? `<code>${escapeHtml(insight.avoided_tools)}</code>` : '-'}</span>
        </div>
        <div>
          <div class="form-label" title="Advisory sequence learned from reflection; not a mandatory workflow unless marked required">Preferred Sequence</div>
          <span>${renderToolSequenceField(insight.preferred_tool_sequence)}</span>
        </div>
        <div>
          <div class="form-label">Supporting Tools</div>
          <span>${renderToolSequenceField(insight.supporting_tools)}</span>
        </div>
        <div>
          <div class="form-label">Sequence Required</div>
          <span>${insight.sequence_required ? 'Yes' : 'No'}</span>
        </div>
        <div>
          <div class="form-label">Primary Intent</div>
          <span>${insight.primary_intent ? escapeHtml(insight.primary_intent) : '-'}</span>
        </div>
        <div>
          <div class="form-label">Source Experience</div>
          <span>${insight.source_experience_id ? `#${escapeHtml(String(insight.source_experience_id))}` : '-'}</span>
        </div>
        <div>
          <div class="form-label">Source Web Conversation</div>
          <span>${insight.source_web_conversation_id ? `<code>${escapeHtml(insight.source_web_conversation_id)}</code>` : '-'}</span>
        </div>
        <div style="grid-column: 1 / -1;">
          <div class="form-label">Source Tool Sequence</div>
          <span>${renderToolSequenceField(insight.source_tool_sequence)}</span>
        </div>
        ${evidence.length > 0 ? `
          <div style="grid-column: 1 / -1;">
            <div class="form-label">Evidence Trail</div>
            <div style="display: grid; gap: var(--space-xs);">
              ${evidence.slice(0, 5).map(item => `
                <div style="font-size: var(--text-sm); color: var(--text-secondary);">
                  <code>#${escapeHtml(String(item.experience_id || '-'))}</code>
                  ${item.web_conversation_id ? `web <code>${escapeHtml(item.web_conversation_id)}</code>` : ''}
                  ${item.action ? ` ${escapeHtml(item.action)}` : ''}
                  ${item.preferred_tool ? ` prefer <code>${escapeHtml(item.preferred_tool)}</code>` : ''}
                  ${Array.isArray(item.tool_sequence) && item.tool_sequence.length ? ` via ${escapeHtml(item.tool_sequence.join(' → '))}` : ''}
                </div>
              `).join('')}
            </div>
          </div>
        ` : ''}
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
    await loadAllInsightsForCounts();
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
    await loadAllExperiencesForCounts();
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
    await loadAllExperiencesForCounts();
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
    await loadAllInsightsForCounts();
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
    await loadAllInsightsForCounts();
    await loadInsights();
  } catch (error) {
    showToast(`Failed to delete: ${error.message}`, 'error');
  }
}

async function runHealthCheck() {
  const modal = document.getElementById('healthModal');
  const body = document.getElementById('healthModalBody');
  
  body.innerHTML = '<div class="loading"><div class="spinner"></div></div>';
  showModal(modal);
  
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

function showAnomalyResults(result) {
  const body = document.getElementById('anomalyModalBody');
  
  if (!result.ok) {
    body.innerHTML = `<div class="empty-state"><div class="empty-state-icon">❌</div><div class="empty-state-title">Detection failed</div><div class="empty-state-desc">${escapeHtml(result.error || 'Unknown error')}</div></div>`;
    return;
  }
  
  // Handle insufficient data case
  if (result.status === 'insufficient_data') {
    body.innerHTML = `
      <div class="empty-state">
        <div class="empty-state-icon">📊</div>
        <div class="empty-state-title">Insufficient Data</div>
        <div class="empty-state-desc">Not enough experiences in the last 7 days to establish a baseline for anomaly detection.</div>
      </div>`;
    return;
  }
  
  const anomalyCount = result.anomalies_found || result.anomalies?.length || 0;
  const avgTurns = result.baseline_avg_turns ?? 'N/A';
  const stdDev = result.baseline_std_dev ?? 'N/A';
  
  let html = `
    <div class="anomaly-stats" style="display: grid; grid-template-columns: repeat(3, 1fr); gap: var(--space-md); margin-bottom: var(--space-lg); padding: var(--space-md); background: var(--bg-secondary); border-radius: var(--radius-md);">
      <div style="text-align: center;">
        <div style="font-size: var(--text-2xl); font-weight: 600; color: ${anomalyCount > 0 ? 'var(--warning)' : 'var(--success)'};">${anomalyCount}</div>
        <div style="font-size: var(--text-sm); color: var(--text-secondary);">Anomalies Found</div>
      </div>
      <div style="text-align: center;">
        <div style="font-size: var(--text-2xl); font-weight: 600; color: var(--text-primary);">${avgTurns}</div>
        <div style="font-size: var(--text-sm); color: var(--text-secondary);">Avg Turns (7d)</div>
      </div>
      <div style="text-align: center;">
        <div style="font-size: var(--text-2xl); font-weight: 600; color: var(--text-primary);">${stdDev}</div>
        <div style="font-size: var(--text-sm); color: var(--text-secondary);">Std Deviation</div>
      </div>
    </div>`;
  
  if (anomalyCount === 0) {
    html += `
      <div class="empty-state" style="padding: var(--space-lg);">
        <div class="empty-state-icon">✅</div>
        <div class="empty-state-title">No Anomalies Detected</div>
        <div class="empty-state-desc">All recent experiences are within normal parameters.</div>
      </div>`;
  } else {
    html += `<div class="anomaly-list" style="display: flex; flex-direction: column; gap: var(--space-md);">`;
    
    for (const anomaly of result.anomalies) {
      const reasonBadges = anomaly.reasons.map(r => {
        if (r.type === 'high_turns') {
          return `<span style="display: inline-block; padding: 2px 8px; background: var(--warning); color: var(--bg-primary); border-radius: var(--radius-sm); font-size: var(--text-xs); margin-right: 4px;">⚡ High Turns: ${r.turns} (z=${r.z_score})</span>`;
        } else if (r.type === 'failed_multi_turn') {
          return `<span style="display: inline-block; padding: 2px 8px; background: var(--error); color: white; border-radius: var(--radius-sm); font-size: var(--text-xs); margin-right: 4px;">❌ Failed after ${r.turns} turns</span>`;
        }
        return `<span style="display: inline-block; padding: 2px 8px; background: var(--text-tertiary); color: var(--bg-primary); border-radius: var(--radius-sm); font-size: var(--text-xs); margin-right: 4px;">${r.type}</span>`;
      }).join('');
      
      html += `
        <div style="padding: var(--space-md); background: var(--bg-secondary); border-radius: var(--radius-md); border-left: 3px solid var(--warning);">
          <div style="font-size: var(--text-sm); color: var(--text-secondary); margin-bottom: var(--space-xs);">Experience #${anomaly.experience_id}</div>
          <div style="font-size: var(--text-base); color: var(--text-primary); margin-bottom: var(--space-sm);">${escapeHtml(anomaly.query)}</div>
          <div>${reasonBadges}</div>
        </div>`;
    }
    
    html += `</div>`;
  }
  
  body.innerHTML = html;
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
    currentExpCompletionGuardFilter = null;
  }
  
  // Reset insight-specific filters when switching away
  if (tab !== 'insights') {
    currentInsightSort = 'updated';
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
  document.getElementById('feedbackFilters').style.display = tab === 'feedback' ? 'block' : 'none';
  
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
  if (insightSortSelect) insightSortSelect.value = 'updated';
  
  // Reset tool filter
  const toolFilter = document.getElementById('expToolFilter');
  if (toolFilter) toolFilter.value = '';

  const completionGuardFilter = document.getElementById('expCompletionGuardFilter');
  if (completionGuardFilter) completionGuardFilter.value = '';
  
  // Update search placeholder
  const searchInput = document.getElementById('searchInput');
  const placeholders = {
    experiences: 'Search experiences...',
    insights: 'Search insights...',
    feedback: 'Search feedback...',
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
    disconnectPaginationObserver(experiencePagination);
    experiencePagination = { offset: 0, total: 0, hasMore: false, loading: false, observer: null };
    try {
      const result = await api.searchExperiences(query, 50, currentExpSort);
      experiencesData = applyExperienceFilters(result.experiences || []);
      allExperiencesData = experiencesData;
      renderExperiences();
    } catch (error) {
      showToast(`Search failed: ${error.message}`, 'error');
    }
  } else if (currentTab === 'insights') {
    disconnectPaginationObserver(insightPagination);
    insightPagination = { offset: 0, total: 0, hasMore: false, loading: false, observer: null };
    try {
      const result = await api.searchInsights(query, 50, currentInsightSort);
      insightsData = result.insights || [];
      allInsightsData = insightsData;
      renderInsights();
    } catch (error) {
      showToast(`Search failed: ${error.message}`, 'error');
    }
  } else if (currentTab === 'feedback') {
    feedbackData = filterFeedbackByQuery(allFeedbackData, query);
    renderFeedback();
  }
}

function filterFeedbackByQuery(entries, query) {
  const normalizedQuery = (query || '').trim().toLowerCase();
  if (!normalizedQuery) return [...(entries || [])];

  return (entries || []).filter(entry => {
    const issues = Array.isArray(entry.issues) ? entry.issues : [];
    const tools = Array.isArray(entry.tools_used) ? entry.tools_used : [];
    const toolRatings = entry.tool_ratings && typeof entry.tool_ratings === 'object'
      ? Object.entries(entry.tool_ratings).flatMap(([tool, data]) => {
          if (data && typeof data === 'object') {
            return [tool, data.note || '', String(data.rating ?? '')];
          }
          return [tool, String(data ?? '')];
        })
      : [];

    const searchableParts = [
      entry.query,
      entry.summary,
      entry.positive,
      entry.final_speech,
      entry.raw_llm_response,
      entry.feedback_model,
      entry.feedback_provider,
      entry.mode,
      entry.session_id,
      entry.timestamp,
      ...tools,
      ...toolRatings,
      ...issues.flatMap(issue => {
        if (!issue || typeof issue !== 'object') return [];
        return [
          issue.category || '',
          issue.description || '',
          issue.suggestion || '',
        ];
      }),
    ];

    return searchableParts
      .filter(Boolean)
      .some(value => String(value).toLowerCase().includes(normalizedQuery));
  });
}

// ============================================================================
// Count Updates
// ============================================================================

function updateExperienceCounts() {
  const all = experienceSummary?.total ?? allExperiencesData.length ?? experiencesData.length;
  const success = experienceSummary?.success ?? allExperiencesData.filter(e => e.outcome_success).length;
  const failed = experienceSummary?.failed ?? allExperiencesData.filter(e => !e.outcome_success).length;
  const noTools = experienceSummary?.tool_count?.none ?? 0;
  const singleTool = experienceSummary?.tool_count?.single ?? 0;
  const multiTool = experienceSummary?.tool_count?.multi ?? 0;
  
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
  const all = insightSummary?.total ?? insightsData.length;
  const positive = insightSummary?.positive ?? insightsData.filter(i => (i.constraint_type || 'positive') === 'positive').length;
  const negative = insightSummary?.negative ?? insightsData.filter(i => i.constraint_type === 'negative').length;
  const eliteConf = insightSummary?.confidence?.elite ?? 0;
  const highConf = insightSummary?.confidence?.high ?? 0;
  const goodConf = insightSummary?.confidence?.good ?? 0;
  const medConf = insightSummary?.confidence?.medium ?? 0;
  const lowConf = insightSummary?.confidence?.low ?? 0;
  
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
  if (hasActiveModal()) return;

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

// ============================================================================
// Utilities
// ============================================================================

function closeAllModals() {
  document.querySelectorAll('.modal-overlay').forEach(m => m.classList.remove('active'));
  closeSidebar();
  setModalOpenState(false);
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

function parseStoredUtcDate(dateStr) {
  if (!dateStr) return null;
  const text = String(dateStr).trim();
  const hasTimezone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(text);
  return new Date(hasTimezone ? text : `${text}Z`);
}

function formatDate(dateStr) {
  if (!dateStr) return 'Unknown';
  const date = parseStoredUtcDate(dateStr);
  if (!date || Number.isNaN(date.getTime())) return String(dateStr);
  return date.toLocaleDateString() + ' ' + date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function formatRecordTimestamp(record, field) {
  return record?.[`${field}_local_display`] || formatDate(record?.[field]);
}

function formatRecordTimestampTitle(record, field) {
  if (!record) return 'Unknown';
  const local = record[`${field}_local_display`] || formatDate(record[field]);
  const utc = record[`${field}_utc_display`] || record[`${field}_utc`] || record[field];
  return `Local: ${local}\nUTC: ${utc}`;
}

function renderTimestampStack(record, field) {
  const local = formatRecordTimestamp(record, field);
  const utc = record?.[`${field}_utc_display`] || record?.[`${field}_utc`] || record?.[field] || 'Unknown';
  return `
    <div class="timestamp-stack" title="${escapeHtml(formatRecordTimestampTitle(record, field))}">
      <span>${escapeHtml(local)}</span>
      <span class="timestamp-utc">${escapeHtml(utc)}</span>
    </div>
  `;
}

function renderCompletionGuardBadge(completionGuard) {
  const status = completionGuard?.status;
  if (!status) return '';
  const safeStatus = String(status).replace(/[^a-z0-9_-]/gi, '').toLowerCase();
  return `<span class="completion-guard-mini ${safeStatus}" title="Completion Guard: ${escapeHtml(status)}">${escapeHtml(getCompletionGuardStatusLabel(status, true))}</span>`;
}

function getCompletionGuardStatus(exp) {
  return exp?.completion_guard?.status || exp?.raw_data?.completion_guard?.status || 'none';
}

function getCompletionGuardStatusLabel(status, compact = false) {
  const labels = {
    accepted: compact ? 'CG accepted' : 'Accepted',
    auto_accepted: compact ? 'CG auto' : 'Auto Accepted',
    repaired: compact ? 'CG repaired' : 'Repaired',
    ticket_created: compact ? 'CG ticket' : 'Ticket Created',
    cancelled: compact ? 'CG cancelled' : 'Cancelled',
    tighten_only: compact ? 'CG tightened' : 'Tighten Only',
    expired: compact ? 'CG expired' : 'Expired',
    superseded: compact ? 'CG superseded' : 'Superseded',
    none: compact ? 'No CG' : 'No Completion Guard'
  };
  return labels[status] || (compact ? `CG ${status}` : status);
}

function getCompletionGuardStatusRank(status) {
  const ranks = {
    repaired: 0,
    ticket_created: 1,
    tighten_only: 2,
    cancelled: 3,
    expired: 4,
    superseded: 5,
    accepted: 6,
    auto_accepted: 7,
    none: 8
  };
  return ranks[status] ?? 9;
}

function getCompletionGuardSortRank(exp) {
  return getCompletionGuardStatusRank(getCompletionGuardStatus(exp));
}

function renderCompletionGuardSummary(completionGuard) {
  const status = completionGuard?.status || 'unknown';
  const note = completionGuard?.note || '';
  const updatedAt = completionGuard?.updated_at || completionGuard?.metadata?.settled_at || '';
  return `
    <div class="completion-guard-summary">
      <span class="completion-guard-mini ${escapeHtml(String(status).replace(/[^a-z0-9_-]/gi, '').toLowerCase())}">${escapeHtml(status)}</span>
      ${updatedAt ? `<span class="timestamp-utc">${escapeHtml(updatedAt)}</span>` : ''}
      ${note ? `<div class="completion-guard-note">${escapeHtml(note)}</div>` : ''}
    </div>
  `;
}

function renderJsonDetailBlock(value, className = '') {
  const text = JSON.stringify(value, null, 2);
  return `<pre class="detail-block json-detail ${className}">${escapeHtml(text)}</pre>`;
}

function truncate(str, length) {
  if (!str) return '';
  return str.length > length ? str.substring(0, length) + '...' : str;
}

function getCurrentSearchQuery() {
  return document.getElementById('searchInput')?.value.trim() || '';
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
