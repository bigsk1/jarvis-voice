/**
 * Jarvis Web UI - Utility Functions
 */

const Utils = {
  /**
   * Generate a unique ID
   */
  generateId() {
    return 'id_' + Math.random().toString(36).substr(2, 9) + Date.now().toString(36);
  },

  /**
   * Escape HTML to prevent XSS
   */
  escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  },

  /**
   * Format timestamp
   */
  formatTime(date = new Date()) {
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  },

  /**
   * Format duration in ms to human readable
   */
  formatDuration(ms) {
    if (ms < 1000) return `${ms}ms`;
    if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
    return `${(ms / 60000).toFixed(1)}m`;
  },

  /**
   * Debounce function
   */
  debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
      const later = () => {
        clearTimeout(timeout);
        func(...args);
      };
      clearTimeout(timeout);
      timeout = setTimeout(later, wait);
    };
  },

  /**
   * Parse markdown to HTML (simple version)
   */
  parseMarkdown(text) {
    // Safety check: ensure text is a string
    if (text === null || text === undefined) {
      return '';
    }
    if (typeof text !== 'string') {
      // If object, try to stringify or extract content
      if (typeof text === 'object') {
        text = text.text || text.content || text.speech || JSON.stringify(text);
      } else {
        text = String(text);
      }
    }
    
    if (typeof marked !== 'undefined') {
      return marked.parse(text);
    }
    // Fallback: basic formatting
    return text
      .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
      .replace(/\*(.*?)\*/g, '<em>$1</em>')
      .replace(/`(.*?)`/g, '<code>$1</code>')
      .replace(/\n/g, '<br>');
  },

  /**
   * Auto-resize textarea
   */
  autoResize(textarea) {
    textarea.style.height = 'auto';
    textarea.style.height = Math.min(textarea.scrollHeight, 150) + 'px';
  },

  /**
   * Scroll element to bottom
   */
  scrollToBottom(element, smooth = true) {
    element.scrollTo({
      top: element.scrollHeight,
      behavior: smooth ? 'smooth' : 'auto'
    });
  },

  /**
   * Show toast notification
   */
  toast(message, type = 'info', duration = 3000) {
    const container = document.getElementById('toastContainer');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    container.appendChild(toast);

    setTimeout(() => {
      toast.style.opacity = '0';
      setTimeout(() => toast.remove(), 300);
    }, duration);
  },

  /**
   * Format JSON for display
   */
  formatJson(obj, indent = 2) {
    try {
      return JSON.stringify(obj, null, indent);
    } catch {
      return String(obj);
    }
  },

  /**
   * Truncate text with ellipsis
   */
  truncate(text, maxLength = 100) {
    if (text.length <= maxLength) return text;
    return text.substring(0, maxLength - 3) + '...';
  },

  /**
   * Store data in localStorage
   */
  storage: {
    get(key, defaultValue = null) {
      try {
        const item = localStorage.getItem(`jarvis_${key}`);
        return item ? JSON.parse(item) : defaultValue;
      } catch {
        return defaultValue;
      }
    },
    set(key, value) {
      try {
        localStorage.setItem(`jarvis_${key}`, JSON.stringify(value));
      } catch (e) {
        console.warn('localStorage error:', e);
      }
    },
    remove(key) {
      localStorage.removeItem(`jarvis_${key}`);
    }
  },

  /**
   * Authentication helpers
   */
  auth: {
    getToken() {
      return localStorage.getItem('jarvis_auth_token');
    },
    
    setToken(token) {
      localStorage.setItem('jarvis_auth_token', token);
      // Also set cookie for server-side checks
      document.cookie = `jarvis_auth=${token}; path=/; max-age=86400; SameSite=Lax`;
    },
    
    clearToken() {
      localStorage.removeItem('jarvis_auth_token');
      document.cookie = 'jarvis_auth=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT';
    },
    
    isAuthenticated() {
      return !!this.getToken();
    },
    
    logout() {
      this.clearToken();
      window.location.href = '/login';
    },
    
    // Get headers with auth token for fetch requests
    getHeaders(additionalHeaders = {}) {
      const headers = { ...additionalHeaders };
      const token = this.getToken();
      if (token) {
        headers['Authorization'] = `Bearer ${token}`;
      }
      return headers;
    },
    
    // Wrapper for fetch that includes auth
    async fetch(url, options = {}) {
      options.headers = this.getHeaders(options.headers || {});
      const response = await fetch(url, options);
      
      // If 401, redirect to login
      if (response.status === 401) {
        this.clearToken();
        window.location.href = `/login?redirect=${encodeURIComponent(window.location.pathname)}`;
        throw new Error('Authentication required');
      }
      
      return response;
    }
  }
};

// Make available globally
window.Utils = Utils;

// =============================================================================
// Lightbox functions
// =============================================================================

window.showImageLightbox = function(imageUrl) {
  const lightbox = document.getElementById('imageLightbox');
  const img = document.getElementById('lightboxImage');
  const downloadBtn = document.getElementById('lightboxDownload');
  
  img.src = imageUrl;
  downloadBtn.href = imageUrl;
  
  // Extract filename for download
  const filename = imageUrl.split('/').pop();
  downloadBtn.download = filename;
  
  lightbox.classList.add('active');
  document.body.style.overflow = 'hidden';
};

window.closeLightbox = function(event) {
  // If event exists and click was on the image, don't close
  if (event && event.target.tagName === 'IMG') {
    return;
  }
  
  const lightbox = document.getElementById('imageLightbox');
  lightbox.classList.remove('active');
  document.body.style.overflow = '';
};

// Close lightbox on Escape key
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    window.closeLightbox();
  }
});

