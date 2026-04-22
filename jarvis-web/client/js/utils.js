/**
 * Jarvis Web UI - Utility Functions
 */

const Utils = {
  _markedConfigured: false,
  _scrollAnimations: new WeakMap(),

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
   * Escape HTML and convert URLs to clickable links (target="_blank")
   */
  escapeHtmlAndLinkify(text) {
    if (text === null || text === undefined) return '';
    const str = String(text);
    const escaped = this.escapeHtml(str);
    // Match http(s) and stash refs, excluding trailing punctuation
    const urlRe = /((?:stash:\/\/|https?:\/\/)[^\s<>"')\]]+)/g;
    return escaped.replace(urlRe, (url) => {
      const href = (this.stashRefToViewerUrl(url) || url).replace(/"/g, '&quot;');
      return `<a href="${href}" target="_blank" rel="noopener noreferrer" class="content-link">${url}</a>`;
    });
  },

  /**
   * Convert stash://space/file refs into the rendered same-origin viewer URL.
   */
  stashRefToViewerUrl(ref) {
    if (!ref || typeof ref !== 'string') {
      return null;
    }
    const clean = ref.trim().replace(/[.,;)\]]+$/g, '');
    const match = clean.match(/^stash:\/\/([^/\s?#]+)\/([^/\s?#]+)/);
    if (!match) {
      return null;
    }
    return `/stash/view/${encodeURIComponent(match[1])}/${encodeURIComponent(match[2])}`;
  },

  /**
   * Convert stash://space/file refs into the raw API URL.
   */
  stashRefToApiUrl(ref) {
    if (!ref || typeof ref !== 'string') {
      return null;
    }
    const clean = ref.trim().replace(/[.,;)\]]+$/g, '');
    const match = clean.match(/^stash:\/\/([^/\s?#]+)\/([^/\s?#]+)/);
    if (!match) {
      return null;
    }
    return `/api/stash/${encodeURIComponent(match[1])}/${encodeURIComponent(match[2])}`;
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

    text = this.normalizePlainTextTables(text);
    text = this.escapeStandaloneTildes(text);
    
    if (typeof marked !== 'undefined') {
      if (!this._markedConfigured) {
        const renderer = new marked.Renderer();
        renderer.link = (hrefOrToken, title, text) => {
          // Support both Marked renderer signatures:
          //   link(href, title, text)
          //   link({ href, title, tokens, text })
          let href = hrefOrToken;
          let label = text;
          let linkTitle = title;

          if (hrefOrToken && typeof hrefOrToken === 'object') {
            href = hrefOrToken.href || '';
            linkTitle = hrefOrToken.title || '';
            label = hrefOrToken.text
              || (hrefOrToken.tokens || []).map(token => token.text || token.raw || '').join('')
              || href;
          }

          const resolvedHref = this.stashRefToViewerUrl(href) || href;
          const safeHref = resolvedHref ? String(resolvedHref).replace(/"/g, '&quot;') : '';
          const safeTitle = linkTitle ? ` title="${this.escapeHtml(linkTitle)}"` : '';
          const safeLabel = this.escapeHtml(label || href || '');

          return `<a href="${safeHref}" target="_blank" rel="noopener noreferrer" class="content-link"${safeTitle}>${safeLabel}</a>`;
        };
        renderer.code = (codeOrToken, infostring, escaped) => {
          let rawCode = codeOrToken;
          let language = infostring || '';

          if (codeOrToken && typeof codeOrToken === 'object') {
            rawCode = codeOrToken.text || '';
            language = codeOrToken.lang || '';
          }

          const codeText = rawCode == null ? '' : String(rawCode);
          const safeCode = this.escapeHtml(codeText);
          const safeLanguage = this.escapeHtml(String(language || '').trim());
          const languageLabel = safeLanguage || 'code';
          const languageClass = safeLanguage ? ` language-${safeLanguage}` : '';

          return `
            <div class="code-block">
              <div class="code-block-header">
                <span class="code-block-language">${languageLabel}</span>
                <button class="code-block-copy" type="button" onclick="Utils.copyCodeBlock(this)">Copy</button>
              </div>
              <pre><code class="${languageClass}">${safeCode}</code></pre>
            </div>
          `;
        };
        marked.use({ renderer, gfm: true, breaks: false });
        this._markedConfigured = true;
      }
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
   * Convert simple tab/aligned text tables into GitHub-flavored Markdown tables.
   * LLMs often emit "Header<TAB>Header<TAB>Header" instead of pipe tables.
   */
  normalizePlainTextTables(text) {
    if (!text || typeof text !== 'string') {
      return text;
    }

    const codeSegments = text.split(/(```[\s\S]*?```|~~~[\s\S]*?~~~)/g);
    return codeSegments
      .map((segment, index) => {
        if (index % 2 === 1) {
          return segment;
        }
        return this.normalizePlainTextTablesSegment(segment);
      })
      .join('');
  },

  normalizePlainTextTablesSegment(segment) {
    const lines = segment.split('\n');
    const output = [];
    let i = 0;

    while (i < lines.length) {
      const firstRow = this.splitPlainTextTableRow(lines[i]);
      if (!firstRow) {
        output.push(lines[i]);
        i += 1;
        continue;
      }

      const rows = [firstRow];
      let j = i + 1;
      while (j < lines.length) {
        const row = this.splitPlainTextTableRow(lines[j]);
        if (!row || row.length !== firstRow.length) {
          break;
        }
        rows.push(row);
        j += 1;
      }

      if (rows.length < 2) {
        output.push(lines[i]);
        i += 1;
        continue;
      }

      if (output.length && output[output.length - 1].trim() !== '') {
        output.push('');
      }
      output.push(this.toMarkdownTable(rows));
      if (j < lines.length && lines[j].trim() !== '') {
        output.push('');
      }
      i = j;
    }

    return output.join('\n');
  },

  splitPlainTextTableRow(line) {
    if (!line || !line.trim()) {
      return null;
    }

    const trimmed = line.trim();
    if (
      trimmed.includes('|')
      || /^(```|~~~)/.test(trimmed)
      || /^[>#]/.test(trimmed)
      || /^[-*+]\s+/.test(trimmed)
      || /^\d+\.\s+/.test(trimmed)
    ) {
      return null;
    }

    let cells = null;
    if (line.includes('\t')) {
      cells = trimmed.split(/\t+/);
    } else if (/\S {2,}\S/.test(line)) {
      cells = trimmed.split(/ {2,}/);
    }

    if (!cells) {
      return null;
    }

    cells = cells.map(cell => cell.trim()).filter(Boolean);
    return cells.length >= 3 ? cells : null;
  },

  toMarkdownTable(rows) {
    const escapeCell = (cell) => String(cell).replace(/\|/g, '\\|');
    const header = rows[0].map(escapeCell);
    const bodyRows = rows.slice(1).map(row => row.map(escapeCell));
    return [
      `| ${header.join(' | ')} |`,
      `| ${header.map(() => '---').join(' | ')} |`,
      ...bodyRows.map(row => `| ${row.join(' | ')} |`)
    ].join('\n');
  },

  /**
   * Keep single "~" approximation markers literal while preserving "~~" markdown.
   * Marked treats lone tildes as strikethrough delimiters in some cases.
   */
  escapeStandaloneTildes(text) {
    if (!text || !text.includes('~')) {
      return text;
    }

    const codeSegments = text.split(/(```[\s\S]*?```|`[^`\n]*`)/g);
    return codeSegments
      .map((segment, index) => {
        if (index % 2 === 1) {
          return segment;
        }
        let escaped = '';
        for (let i = 0; i < segment.length; i++) {
          const char = segment[i];
          if (char !== '~') {
            escaped += char;
            continue;
          }

          const prevChar = i > 0 ? segment[i - 1] : '';
          const nextChar = i < segment.length - 1 ? segment[i + 1] : '';
          const isDoubleTilde = prevChar === '~' || nextChar === '~';
          escaped += isDoubleTilde ? '~' : '&#126;';
        }
        return escaped;
      })
      .join('');
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
  scrollToBottom(element, smooth = true, options = {}) {
    if (!element) return;

    const getTarget = () => Math.max(0, element.scrollHeight - element.clientHeight);
    const existingAnimation = this._scrollAnimations.get(element);
    if (existingAnimation) {
      cancelAnimationFrame(existingAnimation);
      this._scrollAnimations.delete(element);
    }

    const target = getTarget();
    if (!smooth || window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) {
      element.scrollTop = target;
      return;
    }

    const start = element.scrollTop;
    const distance = target - start;
    if (Math.abs(distance) < 2) {
      element.scrollTop = target;
      return;
    }

    // Smooth scroll duration in milliseconds
    const duration = options.duration
      ?? Math.min(2200, Math.max(750, Math.abs(distance) * 0.8));
    const startTime = performance.now();
    const easeInOutQuart = (t) =>
      t < 0.5
        ? 8 * t * t * t * t
        : 1 - Math.pow(-2 * t + 2, 4) / 2;

    const step = (now) => {
      const elapsed = now - startTime;
      const progress = Math.min(1, elapsed / duration);
      const currentTarget = getTarget();

      element.scrollTop = start + (currentTarget - start) * easeInOutQuart(progress);

      if (progress < 1) {
        this._scrollAnimations.set(element, requestAnimationFrame(step));
      } else {
        element.scrollTop = currentTarget;
        this._scrollAnimations.delete(element);
      }
    };

    this._scrollAnimations.set(element, requestAnimationFrame(step));
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

  async copyCodeBlock(button) {
    const container = button?.closest('.code-block');
    const codeEl = container?.querySelector('code');
    const codeText = codeEl?.textContent || '';

    if (!codeText) {
      this.toast('Nothing to copy', 'warning');
      return;
    }

    try {
      if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
        await navigator.clipboard.writeText(codeText);
      } else {
        this.copyTextFallback(codeText);
      }
      const original = button.textContent;
      button.textContent = 'Copied';
      button.disabled = true;
      this.toast('Code copied', 'success', 1500);
      setTimeout(() => {
        button.textContent = original;
        button.disabled = false;
      }, 1200);
    } catch (error) {
      console.error('[Utils] Failed to copy code block:', error);
      this.toast('Failed to copy code', 'error');
    }
  },

  copyTextFallback(text) {
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.setAttribute('readonly', '');
    textarea.style.position = 'fixed';
    textarea.style.top = '-9999px';
    textarea.style.left = '-9999px';
    textarea.style.opacity = '0';
    document.body.appendChild(textarea);

    const selection = document.getSelection();
    const originalRange = selection && selection.rangeCount > 0
      ? selection.getRangeAt(0)
      : null;

    textarea.focus();
    textarea.select();
    textarea.setSelectionRange(0, textarea.value.length);

    const success = document.execCommand('copy');
    document.body.removeChild(textarea);

    if (selection) {
      selection.removeAllRanges();
      if (originalRange) {
        selection.addRange(originalRange);
      }
    }

    if (!success) {
      throw new Error('document.execCommand("copy") failed');
    }
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
  if (!lightbox || !img || !downloadBtn) {
    window.open(imageUrl, '_blank', 'noopener,noreferrer');
    return;
  }
  
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
  if (!lightbox) {
    return;
  }
  lightbox.classList.remove('active');
  document.body.style.overflow = '';
};

// Close lightbox on Escape key
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    window.closeLightbox();
  }
});
