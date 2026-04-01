/**
 * API Client for Jarvis Memory Browser
 */

class MemoryAPI {
  constructor() {
    this.baseUrl = '';
    this.mode = 'cloud';
  }
  
  setMode(mode) {
    this.mode = mode;
  }
  
  async fetch(endpoint, options = {}) {
    const url = `${this.baseUrl}${endpoint}`;
    const separator = endpoint.includes('?') ? '&' : '?';
    const fullUrl = `${url}${separator}mode=${this.mode}`;
    
    try {
      const response = await fetch(fullUrl, {
        headers: {
          'Content-Type': 'application/json',
          ...options.headers
        },
        ...options
      });
      
      const data = await response.json();
      
      if (!response.ok) {
        throw new Error(data.error || `HTTP ${response.status}`);
      }
      
      return data;
    } catch (error) {
      console.error(`API Error: ${endpoint}`, error);
      throw error;
    }
  }
  
  // =========================================================================
  // Status
  // =========================================================================
  
  async getStatus() {
    return this.fetch('/api/status');
  }
  
  // =========================================================================
  // Memories
  // =========================================================================
  
  async listMemories(options = {}) {
    const params = new URLSearchParams();
    if (options.category) params.set('category', options.category);
    if (options.limit) params.set('limit', options.limit);
    if (options.offset) params.set('offset', options.offset);
    if (options.sort_by) params.set('sort_by', options.sort_by);
    if (options.sort_order) params.set('sort_order', options.sort_order);
    
    const query = params.toString();
    return this.fetch(`/api/memories${query ? '?' + query : ''}`);
  }
  
  async getMemory(id) {
    return this.fetch(`/api/memories/${id}`);
  }
  
  async searchMemories(query, limit = 50) {
    return this.fetch(`/api/memories/search?q=${encodeURIComponent(query)}&limit=${limit}`);
  }
  
  async createMemory(data) {
    return this.fetch('/api/memories', {
      method: 'POST',
      body: JSON.stringify(data)
    });
  }
  
  async updateMemory(id, data) {
    return this.fetch(`/api/memories/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data)
    });
  }
  
  async deleteMemory(id) {
    return this.fetch(`/api/memories/${id}`, {
      method: 'DELETE'
    });
  }
  
  async reembedMemory(id) {
    return this.fetch(`/api/memories/${id}/reembed`, {
      method: 'POST'
    });
  }
  
  async getCategories() {
    return this.fetch('/api/memories/categories');
  }
  
  // =========================================================================
  // Stats
  // =========================================================================
  
  async getStats() {
    return this.fetch('/api/stats');
  }
  
  async getMemoryStats() {
    return this.fetch('/api/stats/memory');
  }
  
  // =========================================================================
  // Conversations
  // =========================================================================
  
  async listConversations(options = {}) {
    const params = new URLSearchParams();
    if (options.limit) params.set('limit', options.limit);
    if (options.offset) params.set('offset', options.offset);
    
    const query = params.toString();
    return this.fetch(`/api/conversations${query ? '?' + query : ''}`);
  }
  
  async searchConversations(query, limit = 50) {
    return this.fetch(`/api/conversations/search?q=${encodeURIComponent(query)}&limit=${limit}`);
  }
  
  async getConversationStats() {
    return this.fetch('/api/conversations/stats');
  }
  
  // =========================================================================
  // Intel Files
  // =========================================================================
  
  async listIntelFiles() {
    return this.fetch('/api/intel/files');
  }
  
  async getIntelFile(filename) {
    return this.fetch(`/api/intel/files/${encodeURIComponent(filename)}`);
  }
  
  async updateIntelFile(filename, content) {
    return this.fetch(`/api/intel/files/${encodeURIComponent(filename)}`, {
      method: 'PUT',
      body: JSON.stringify({ content })
    });
  }
  
  async createIntelFile(filename, content) {
    return this.fetch('/api/intel/files', {
      method: 'POST',
      body: JSON.stringify({ filename, content })
    });
  }
  
  async deleteIntelFile(filename) {
    return this.fetch(`/api/intel/files/${encodeURIComponent(filename)}`, {
      method: 'DELETE'
    });
  }
  
  async ingestIntel() {
    return this.fetch('/api/intel/ingest', {
      method: 'POST'
    });
  }

  // =========================================================================
  // Reminders
  // =========================================================================

  async listReminders(options = {}) {
    const params = new URLSearchParams();
    if (options.status) params.set('status', options.status);
    if (options.limit) params.set('limit', options.limit);
    const query = params.toString();
    return this.fetch(`/api/reminders${query ? '?' + query : ''}`);
  }

  async getReminder(id) {
    return this.fetch(`/api/reminders/${id}`);
  }

  async createReminder(data) {
    return this.fetch('/api/reminders', {
      method: 'POST',
      body: JSON.stringify(data)
    });
  }

  async updateReminder(id, data) {
    return this.fetch(`/api/reminders/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data)
    });
  }

  async cancelReminder(id) {
    return this.fetch(`/api/reminders/${id}`, {
      method: 'DELETE'
    });
  }

  async deleteReminder(id) {
    return this.fetch(`/api/reminders/${id}?permanent=true`, {
      method: 'DELETE'
    });
  }

  async acknowledgeReminder(id) {
    return this.fetch(`/api/reminders/${id}/acknowledge`, {
      method: 'POST'
    });
  }

  async acknowledgeAllReminders(status = 'triggered') {
    return this.fetch(`/api/reminders/acknowledge-all?status=${encodeURIComponent(status)}`, {
      method: 'POST'
    });
  }

  // =========================================================================
  // Scheduled Tasks
  // =========================================================================

  async listScheduledTasks(options = {}) {
    const params = new URLSearchParams();
    if (options.status) params.set('status', options.status);
    if (options.limit) params.set('limit', options.limit);
    const query = params.toString();
    return this.fetch(`/api/scheduled-tasks${query ? '?' + query : ''}`);
  }

  async getScheduledTask(id) {
    return this.fetch(`/api/scheduled-tasks/${id}`);
  }

  async createScheduledTask(data) {
    return this.fetch('/api/scheduled-tasks', {
      method: 'POST',
      body: JSON.stringify(data)
    });
  }

  async updateScheduledTask(id, data) {
    return this.fetch(`/api/scheduled-tasks/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data)
    });
  }

  async cancelScheduledTask(id) {
    return this.fetch(`/api/scheduled-tasks/${id}`, {
      method: 'DELETE'
    });
  }

  async deleteScheduledTask(id) {
    return this.fetch(`/api/scheduled-tasks/${id}?permanent=true`, {
      method: 'DELETE'
    });
  }

  async runScheduledTaskNow(id) {
    return this.fetch(`/api/scheduled-tasks/${id}/run`, {
      method: 'POST'
    });
  }

  async listScheduledTaskRuns(id, limit = 20) {
    return this.fetch(`/api/scheduled-tasks/${id}/runs?limit=${limit}`);
  }
}

// Global API instance
const api = new MemoryAPI();
