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
    if (options.sort) params.set('sort', options.sort);
    if (options.tool_count) params.set('tool_count', options.tool_count);
    if (options.tool) params.set('tool', options.tool);
    if (options.completion_guard_status) params.set('completion_guard_status', options.completion_guard_status);
    
    const query = params.toString();
    return this.fetch(`/api/experiences${query ? '?' + query : ''}`);
  }

  async getExperienceSummary() {
    return this.fetch('/api/experiences/summary');
  }
  
  async getExperience(id) {
    return this.fetch(`/api/experiences/${id}`);
  }
  
  async searchExperiences(query, limit = 50, sort = 'date') {
    return this.fetch(`/api/experiences/search?q=${encodeURIComponent(query)}&limit=${limit}&sort=${encodeURIComponent(sort)}`);
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
    if (options.confidence_tier) params.set('confidence_tier', options.confidence_tier);
    if (options.sort) params.set('sort', options.sort);
    
    const query = params.toString();
    return this.fetch(`/api/insights${query ? '?' + query : ''}`);
  }

  async getInsightSummary() {
    return this.fetch('/api/insights/summary');
  }
  
  async getInsight(id) {
    return this.fetch(`/api/insights/${id}`);
  }
  
  async searchInsights(query, limit = 50, sort = 'updated') {
    return this.fetch(`/api/insights/search?q=${encodeURIComponent(query)}&limit=${limit}&sort=${encodeURIComponent(sort)}`);
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
  
  async deleteReflection(id) {
    return this.fetch(`/api/stats/reflection-queue/${id}`, {
      method: 'DELETE'
    });
  }
  
  async deleteAllReflections() {
    return this.fetch('/api/stats/reflection-queue', {
      method: 'DELETE'
    });
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
  
  // =========================================================================
  // Feedback
  // =========================================================================
  
  async listFeedback(options = {}) {
    const params = new URLSearchParams();
    if (options.days) params.set('days', options.days);
    if (options.rating_max) params.set('rating_max', options.rating_max);
    if (options.rating_min) params.set('rating_min', options.rating_min);
    if (options.limit) params.set('limit', options.limit);
    
    const query = params.toString();
    return this.fetch(`/api/feedback${query ? '?' + query : ''}`);
  }
  
  async getFeedbackStats(days = 30) {
    return this.fetch(`/api/feedback/stats?days=${days}`);
  }
  
  async getFeedbackFiles() {
    return this.fetch('/api/feedback/files');
  }
}

// Global API instance
const api = new IntelligenceAPI();
