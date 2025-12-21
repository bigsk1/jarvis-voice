/**
 * API Client for Jarvis Intelligence Dashboard
 */

class IntelligenceAPI {
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
  // Experiences
  // =========================================================================
  
  async listExperiences(options = {}) {
    const params = new URLSearchParams();
    if (options.limit) params.set('limit', options.limit);
    if (options.offset) params.set('offset', options.offset);
    if (options.success_only !== undefined) params.set('success_only', options.success_only);
    
    const query = params.toString();
    return this.fetch(`/api/experiences${query ? '?' + query : ''}`);
  }
  
  async getExperience(id) {
    return this.fetch(`/api/experiences/${id}`);
  }
  
  async searchExperiences(query, limit = 50) {
    return this.fetch(`/api/experiences/search?q=${encodeURIComponent(query)}&limit=${limit}`);
  }
  
  async updateExperience(id, data) {
    return this.fetch(`/api/experiences/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data)
    });
  }
  
  async deleteExperience(id) {
    return this.fetch(`/api/experiences/${id}`, {
      method: 'DELETE'
    });
  }
  
  async reembedExperience(id) {
    return this.fetch(`/api/experiences/${id}/reembed`, {
      method: 'POST'
    });
  }
  
  // =========================================================================
  // Insights
  // =========================================================================
  
  async listInsights(options = {}) {
    const params = new URLSearchParams();
    if (options.limit) params.set('limit', options.limit);
    if (options.offset) params.set('offset', options.offset);
    if (options.constraint_type) params.set('constraint_type', options.constraint_type);
    if (options.min_confidence) params.set('min_confidence', options.min_confidence);
    
    const query = params.toString();
    return this.fetch(`/api/insights${query ? '?' + query : ''}`);
  }
  
  async getInsight(id) {
    return this.fetch(`/api/insights/${id}`);
  }
  
  async searchInsights(query, limit = 50) {
    return this.fetch(`/api/insights/search?q=${encodeURIComponent(query)}&limit=${limit}`);
  }
  
  async updateInsight(id, data) {
    return this.fetch(`/api/insights/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data)
    });
  }
  
  async deleteInsight(id) {
    return this.fetch(`/api/insights/${id}`, {
      method: 'DELETE'
    });
  }
  
  async reembedInsight(id) {
    return this.fetch(`/api/insights/${id}/reembed`, {
      method: 'POST'
    });
  }
  
  async getToolPerformance() {
    return this.fetch('/api/insights/tool-performance');
  }
  
  // =========================================================================
  // Stats
  // =========================================================================
  
  async getStats() {
    return this.fetch('/api/stats');
  }
  
  async getReflectionQueue(limit = 50) {
    return this.fetch(`/api/stats/reflection-queue?limit=${limit}`);
  }
  
  async getMetaKnowledge(type = null) {
    const query = type ? `?type=${encodeURIComponent(type)}` : '';
    return this.fetch(`/api/stats/meta-knowledge${query}`);
  }
  
  // =========================================================================
  // Maintenance
  // =========================================================================
  
  async triggerReflection(batchSize = 5) {
    return this.fetch(`/api/maintenance/reflect?batch_size=${batchSize}`, {
      method: 'POST'
    });
  }
  
  async runDecay() {
    return this.fetch('/api/maintenance/decay', { method: 'POST' });
  }
  
  async runAnomalyDetection() {
    return this.fetch('/api/maintenance/anomaly', { method: 'POST' });
  }
  
  async runMetaCognition() {
    return this.fetch('/api/maintenance/meta-cognition', { method: 'POST' });
  }
  
  async runAllMaintenance() {
    return this.fetch('/api/maintenance/all', { method: 'POST' });
  }
  
  async checkHealth() {
    return this.fetch('/api/maintenance/health');
  }
}

// Global API instance
const api = new IntelligenceAPI();

