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
   * Remove BMP private-use citation placeholders (e.g. wrapped turn0search0 tokens)
   * that some models emit; keeps normal text and URLs intact.
   */
  stripLlmCitationArtifacts(text) {
    if (text === null || text === undefined) return '';
    let s = String(text).replace(/[\uE000-\uF8FF]/g, '');
    s = s.replace(/\bcite\s*turn\d+\w*/gi, '');
    s = s.replace(/\bturn\d+(?:search|news)\d+\b/gi, '');
    return s.replace(/[ \t]{2,}/g, ' ');
  },

  /**
   * Sanitize http(s) URLs for HTML attributes (src/href).
   * Do not run generic escapeHtml() on whole URLs — it can break valid image links.
   */
  safeHttpUrlForAttr(raw) {
    if (raw === null || raw === undefined) return '';
    const s = String(raw).trim();
    if (!s) return '';
    try {
      const u = new URL(s);
      if (u.protocol !== 'http:' && u.protocol !== 'https:') return '';
      return u.href
        .replace(/&/g, '&amp;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
    } catch {
      return '';
    }
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
   * Strip LLM-style outer ```markdown ... ``` wrapper when present.
   * Nested fences (e.g. ```crypto-chart) break marked if the wrapper remains.
   */
  unwrapOuterMarkdownFence(text) {
    if (!text) return text;
    const trimmed = String(text).trim();
    const openMatch = trimmed.match(/^```(?:markdown|md)(?:\s*\n|\s*$)/i);
    if (!openMatch) return text;
    const start = openMatch[0].length;
    const end = trimmed.lastIndexOf('```');
    if (end <= start) return text;
    return trimmed.slice(start, end).trim();
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

    text = this.unwrapOuterMarkdownFence(text);
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
          const safeLanguage = this.escapeHtml(String(language || '').trim());
          if (safeLanguage === 'crypto-chart') {
            const encodedConfig = encodeURIComponent(codeText);
            return `
              <div class="crypto-chart-embed" data-crypto-chart="${encodedConfig}">
                <div class="crypto-chart-loading">Loading chart…</div>
              </div>
            `;
          }

          const safeCode = this.escapeHtml(codeText);
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
   * Give markdown tables their own horizontal scroll area and a simple
   * always-visible scrollbar below the table when the table overflows.
   */
  setupScrollableTables(root = document) {
    const rootEl = root || document;
    const tables = rootEl.querySelectorAll?.('.message-bubble table') || [];

    tables.forEach((table) => {
      if (table.closest('.markdown-table-scroll')) {
        return;
      }

      const wrap = document.createElement('div');
      wrap.className = 'markdown-table-wrap';

      const scroll = document.createElement('div');
      scroll.className = 'markdown-table-scroll';
      scroll.setAttribute('role', 'region');
      scroll.setAttribute('aria-label', 'Scrollable table');
      scroll.tabIndex = 0;

      const bar = document.createElement('div');
      bar.className = 'markdown-table-bar';
      bar.setAttribute('aria-hidden', 'true');

      const thumb = document.createElement('div');
      thumb.className = 'markdown-table-thumb';
      bar.appendChild(thumb);

      table.parentNode.insertBefore(wrap, table);
      scroll.appendChild(table);
      wrap.appendChild(scroll);
      wrap.appendChild(bar);
    });

    const wrappers = rootEl.querySelectorAll?.('.markdown-table-wrap') || [];
    wrappers.forEach((wrap) => {
      const scroll = wrap.querySelector('.markdown-table-scroll');
      const bar = wrap.querySelector('.markdown-table-bar');
      const thumb = wrap.querySelector('.markdown-table-thumb');
      if (!scroll || !bar || !thumb) {
        return;
      }

      const updateState = () => {
        const maxScroll = Math.max(0, scroll.scrollWidth - scroll.clientWidth);
        const isScrollable = maxScroll > 1;
        wrap.classList.toggle('is-scrollable', isScrollable);
        if (!isScrollable) {
          thumb.style.width = '';
          thumb.style.transform = '';
          return;
        }

        const barWidth = bar.clientWidth || scroll.clientWidth;
        const thumbWidth = Math.max(28, Math.round((scroll.clientWidth / scroll.scrollWidth) * barWidth));
        const maxThumbLeft = Math.max(0, barWidth - thumbWidth);
        const thumbLeft = maxScroll > 0 ? (scroll.scrollLeft / maxScroll) * maxThumbLeft : 0;
        thumb.style.width = `${thumbWidth}px`;
        thumb.style.transform = `translateX(${thumbLeft}px)`;
      };

      if (!wrap.dataset.tableScrollSetup) {
        wrap.dataset.tableScrollSetup = 'true';
        scroll.addEventListener('scroll', updateState, { passive: true });

        const setScrollFromClientX = (clientX) => {
          const rect = bar.getBoundingClientRect();
          const thumbWidth = thumb.offsetWidth || 28;
          const maxThumbLeft = Math.max(1, rect.width - thumbWidth);
          const targetThumbLeft = Math.min(
            maxThumbLeft,
            Math.max(0, clientX - rect.left - thumbWidth / 2)
          );
          const maxScroll = Math.max(0, scroll.scrollWidth - scroll.clientWidth);
          scroll.scrollLeft = (targetThumbLeft / maxThumbLeft) * maxScroll;
        };

        let dragging = false;
        bar.addEventListener('pointerdown', (event) => {
          dragging = true;
          bar.setPointerCapture?.(event.pointerId);
          setScrollFromClientX(event.clientX);
          event.preventDefault();
        });
        bar.addEventListener('pointermove', (event) => {
          if (dragging) {
            setScrollFromClientX(event.clientX);
          }
        });
        const stopDragging = (event) => {
          dragging = false;
          bar.releasePointerCapture?.(event.pointerId);
        };
        bar.addEventListener('pointerup', stopDragging);
        bar.addEventListener('pointercancel', stopDragging);

        if (typeof ResizeObserver !== 'undefined') {
          const resizeObserver = new ResizeObserver(updateState);
          resizeObserver.observe(wrap);
          resizeObserver.observe(scroll);
        }
      }

      updateState();
      setTimeout(updateState, 0);
    });
  },

  hydrateRichContent(root = document) {
    this.setupScrollableTables(root);
    return this.hydrateCryptoCharts(root);
  },

  async hydrateCryptoCharts(root = document) {
    const containers = root?.querySelectorAll?.('.crypto-chart-embed[data-crypto-chart]') || [];
    if (!containers.length) {
      return;
    }
    await Promise.all(Array.from(containers).map((container) => this._hydrateCryptoChartContainer(container)));
  },

  async _hydrateCryptoChartContainer(container) {
    if (!container || container.dataset.chartHydrated === 'true') {
      return;
    }
    container.dataset.chartHydrated = 'true';

    let config;
    try {
      config = JSON.parse(decodeURIComponent(container.dataset.cryptoChart || ''));
    } catch (error) {
      this._renderCryptoChartError(container, 'Invalid chart config');
      return;
    }

    if (!config || typeof config !== 'object') {
      this._renderCryptoChartError(container, 'Missing chart config');
      return;
    }

    if (Array.isArray(config.series?.prices) && config.series.prices.length) {
      this._renderCryptoChart(container, config);
      return;
    }

    if (!config.endpoint) {
      this._renderCryptoChartError(container, 'Chart config needs series.prices or endpoint');
      return;
    }

    try {
      const response = await fetch(config.endpoint, {
        headers: { Accept: 'application/json' }
      });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const payload = await response.json();
      const data = payload?.data || payload;
      this._renderCryptoChart(container, {
        ...config,
        ...data,
        endpoint: config.endpoint
      });
    } catch (error) {
      this._renderCryptoChartError(container, `Failed to load chart: ${error.message}`);
    }
  },

  _renderCryptoChartError(container, message) {
    container.classList.add('is-error');
    container.innerHTML = `
      <div class="crypto-chart-shell">
        <div class="crypto-chart-error">${this.escapeHtml(message)}</div>
      </div>
    `;
  },

  _renderCryptoChart(container, config) {
    const prices = Array.isArray(config?.series?.prices) ? config.series.prices : [];
    if (!prices.length) {
      this._renderCryptoChartError(container, 'No price series available');
      return;
    }

    const title = config.title || `${config.coin || config.coin_id || 'Crypto'} ${config.range_label || 'chart'}`;
    const subtitleParts = [];
    if (config.vs_currency) subtitleParts.push(String(config.vs_currency).toUpperCase());
    if (config.points_returned) subtitleParts.push(`${config.points_returned} pts`);
    const currentPrice = Number(config.current_price ?? prices[prices.length - 1]?.value ?? 0);
    const changePercent = Number(config.change_percent ?? 0);
    const positive = changePercent >= 0;
    const svg = this._buildCryptoChartSvg(prices, { positive });
    const rangeLabel = config.range_label || (config.days ? `${config.days}-day` : 'chart');
    const currentLabel = Number.isFinite(currentPrice)
      ? this._formatChartCurrency(currentPrice, config.vs_currency || 'usd')
      : 'n/a';
    const changeLabel = `${positive ? '+' : ''}${changePercent.toFixed(2)}%`;
    const startLabel = prices[0]?.iso ? this._formatChartDate(prices[0].iso) : '';
    const endLabel = prices[prices.length - 1]?.iso ? this._formatChartDate(prices[prices.length - 1].iso) : '';

    container.classList.toggle('is-positive', positive);
    container.classList.toggle('is-negative', !positive);
    container.innerHTML = `
      <div class="crypto-chart-shell">
        <div class="crypto-chart-header">
          <div>
            <div class="crypto-chart-title">${this.escapeHtml(title)}</div>
            <div class="crypto-chart-subtitle">${this.escapeHtml([rangeLabel, ...subtitleParts].join(' • '))}</div>
          </div>
          <div class="crypto-chart-metrics">
            <div class="crypto-chart-price">${this.escapeHtml(currentLabel)}</div>
            <div class="crypto-chart-change">${this.escapeHtml(changeLabel)}</div>
          </div>
        </div>
        <div class="crypto-chart-viewport">${svg}</div>
        <div class="crypto-chart-axis">
          <span>${this.escapeHtml(startLabel)}</span>
          <span>${this.escapeHtml(endLabel)}</span>
        </div>
      </div>
    `;
  },

  _buildCryptoChartSvg(points, { positive = true } = {}) {
    const width = 860;
    const height = 320;
    const padTop = 18;
    const padRight = 18;
    const padBottom = 42;
    const padLeft = 18;
    const plotWidth = width - padLeft - padRight;
    const plotHeight = height - padTop - padBottom;
    const values = points.map((point) => Number(point.value)).filter((value) => Number.isFinite(value));
    const min = Math.min(...values);
    const max = Math.max(...values);
    const range = max - min || Math.max(1, Math.abs(max) * 0.02 || 1);
    const topValue = max + range * 0.08;
    const bottomValue = min - range * 0.08;
    const color = positive ? '#32c48d' : '#ff6b6b';
    const stroke = positive ? '#79f0b2' : '#ff9f9f';
    const uid = `chart-${points.length}-${Math.round(values[values.length - 1] || 0)}`;

    const xAt = (index) => padLeft + (plotWidth * index) / Math.max(1, points.length - 1);
    const yAt = (value) => padTop + ((topValue - value) / Math.max(1e-9, topValue - bottomValue)) * plotHeight;

    const linePath = points.map((point, index) => {
      const x = xAt(index);
      const y = yAt(Number(point.value));
      return `${index === 0 ? 'M' : 'L'} ${x.toFixed(2)} ${y.toFixed(2)}`;
    }).join(' ');

    const areaPath = `${linePath} L ${xAt(points.length - 1).toFixed(2)} ${(padTop + plotHeight).toFixed(2)} L ${xAt(0).toFixed(2)} ${(padTop + plotHeight).toFixed(2)} Z`;
    const gridLines = [0, 0.33, 0.66, 1].map((ratio) => {
      const y = padTop + plotHeight * ratio;
      return `<line x1="${padLeft}" y1="${y.toFixed(2)}" x2="${width - padRight}" y2="${y.toFixed(2)}" class="crypto-chart-grid" />`;
    }).join('');
    const lastX = xAt(points.length - 1);
    const lastY = yAt(Number(points[points.length - 1].value));

    return `
      <svg class="crypto-chart-svg" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="Crypto price chart">
        <defs>
          <linearGradient id="${uid}-fill" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stop-color="${color}" stop-opacity="0.34"></stop>
            <stop offset="100%" stop-color="${color}" stop-opacity="0.03"></stop>
          </linearGradient>
          <filter id="${uid}-glow" x="-20%" y="-20%" width="140%" height="140%">
            <feGaussianBlur stdDeviation="4" result="blur"></feGaussianBlur>
            <feMerge>
              <feMergeNode in="blur"></feMergeNode>
              <feMergeNode in="SourceGraphic"></feMergeNode>
            </feMerge>
          </filter>
        </defs>
        <rect x="0" y="0" width="${width}" height="${height}" rx="24" class="crypto-chart-bg"></rect>
        ${gridLines}
        <path d="${areaPath}" fill="url(#${uid}-fill)"></path>
        <path d="${linePath}" fill="none" stroke="${stroke}" stroke-width="4" stroke-linecap="round" stroke-linejoin="round" filter="url(#${uid}-glow)"></path>
        <circle cx="${lastX.toFixed(2)}" cy="${lastY.toFixed(2)}" r="6" fill="${stroke}" class="crypto-chart-dot"></circle>
      </svg>
    `;
  },

  _formatChartCurrency(value, vsCurrency = 'usd') {
    const currency = String(vsCurrency || 'usd').toUpperCase();
    if (currency === 'USD') {
      if (value >= 1000) return `$${Math.round(value).toLocaleString()}`;
      if (value >= 1) return `$${value.toFixed(2)}`;
      if (value >= 0.01) return `$${value.toFixed(4)}`;
      return `$${value.toFixed(8)}`;
    }
    return `${value.toLocaleString(undefined, { maximumFractionDigits: 4 })} ${currency}`;
  },

  _formatChartDate(iso) {
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) {
      return '';
    }
    return date.toLocaleDateString([], { month: 'short', day: 'numeric' });
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

  persistentToast(message, type = 'warning', id = 'persistent-toast', onClose = null) {
    const container = document.getElementById('toastContainer');
    if (!container) return null;

    this.removeToast(id);
    const toast = document.createElement('div');
    toast.className = `toast ${type} persistent`;
    toast.dataset.toastId = id;

    const text = document.createElement('span');
    text.className = 'toast-message';
    text.textContent = message;

    const close = document.createElement('button');
    close.type = 'button';
    close.className = 'toast-close';
    close.setAttribute('aria-label', 'Dismiss warning');
    close.textContent = '×';
    close.addEventListener('click', () => {
      onClose?.();
      toast.remove();
    });

    toast.append(text, close);
    container.appendChild(toast);
    return toast;
  },

  removeToast(id) {
    const toast = document.querySelector(`[data-toast-id="${CSS.escape(id)}"]`);
    toast?.remove();
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
// Missing media fallbacks (shared placeholder assets in /assets/)
// =============================================================================

window.JarvisMediaFallback = {
  imageUrl: '/assets/image-unavailable.jpg',
  videoUrl: '/assets/video-unavailable.jpg',

  _isJarvisMediaUrl(src) {
    return /\/api\/(images|uploads|stash|videos)\//.test(src || '');
  },

  _videoSource(video) {
    if (!video) return '';
    const source = video.querySelector('source');
    return source?.getAttribute('src') || video.getAttribute('src') || video.currentSrc || '';
  },

  applyImage(img) {
    if (!img || img.dataset.fallbackApplied) return;
    const src = img.getAttribute('src') || '';
    if (!this._isJarvisMediaUrl(src)) return;
    img.dataset.fallbackApplied = '1';
    img.src = this.imageUrl;
    if (!img.alt || img.alt === 'Attached image') {
      img.alt = 'Image no longer available';
    }
    img.classList.add('media-unavailable');
  },

  applyVideo(video) {
    if (!video || video.dataset.fallbackApplied) return;
    const sourceSrc = this._videoSource(video);
    if (!this._isJarvisMediaUrl(sourceSrc)) return;
    video.dataset.fallbackApplied = '1';
    const poster = video.getAttribute('poster') || this.videoUrl;
    const img = document.createElement('img');
    img.src = poster;
    img.alt = 'Video no longer available';
    img.className = 'video-unavailable-fallback media-unavailable';
    img.loading = 'lazy';
    img.addEventListener('error', () => {
      img.src = this.videoUrl;
    }, { once: true });
    video.replaceWith(img);
  },

  bindImage(img) {
    if (!img || img.dataset.fallbackBound) return;
    img.dataset.fallbackBound = '1';
    img.addEventListener('error', () => this.applyImage(img), { once: true });
  },

  bindVideo(video) {
    if (!video || video.dataset.fallbackBound) return;
    video.dataset.fallbackBound = '1';
    video.addEventListener('error', () => this.applyVideo(video), { once: true });
    this.probeVideo(video);
  },

  async probeVideo(video) {
    const sourceSrc = this._videoSource(video);
    if (!sourceSrc || !this._isJarvisMediaUrl(sourceSrc) || video.dataset.fallbackApplied) {
      return;
    }
    try {
      const response = await fetch(sourceSrc, {
        method: 'HEAD',
        credentials: 'same-origin',
      });
      if (!response.ok) {
        this.applyVideo(video);
      }
    } catch {
      this.applyVideo(video);
    }
  },

  bindRoot(root) {
    if (!root) return;
    root.querySelectorAll('img').forEach((img) => this.bindImage(img));
    root.querySelectorAll('video').forEach((video) => this.bindVideo(video));
  },
};

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

  img.onerror = () => {
    if (window.JarvisMediaFallback) {
      window.JarvisMediaFallback.applyImage(img);
    }
  };
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
