class LogsViewerApp {
  constructor() {
    this.state = {
      folders: [],
      selectedFolder: '',
      folderFilter: '',
      files: [],
      fileOffset: 0,
      hasMoreFiles: false,
      selectedFile: '',
      fileSearch: '',
      extension: '',
      days: '',
      sort: 'newest',
      contentOffset: 0,
      hasMoreContent: false,
      contentPath: '',
      contentViewType: '',
      contentRecords: [],
      contentLines: [],
      markdownContent: '',
      mobileStage: 'folders',
    };

    this.elements = {
      folderList: document.getElementById('folderList'),
      folderFilterInput: document.getElementById('folderFilterInput'),
      refreshFoldersBtn: document.getElementById('refreshFoldersBtn'),
      selectedFolderLabel: document.getElementById('selectedFolderLabel'),
      fileSummary: document.getElementById('fileSummary'),
      fileSearchInput: document.getElementById('fileSearchInput'),
      fileList: document.getElementById('fileList'),
      sortSelect: document.getElementById('sortSelect'),
      loadMoreFilesBtn: document.getElementById('loadMoreFilesBtn'),
      selectedFileLabelBtn: document.getElementById('selectedFileLabelBtn'),
      selectedFileLabel: document.getElementById('selectedFileLabel'),
      refreshContentBtn: document.getElementById('refreshContentBtn'),
      viewerSummary: document.getElementById('viewerSummary'),
      viewerContent: document.getElementById('viewerContent'),
      loadMoreContentBtn: document.getElementById('loadMoreContentBtn'),
      backToFoldersBtn: document.getElementById('backToFoldersBtn'),
      backToFilesBtn: document.getElementById('backToFilesBtn'),
      extensionChips: document.getElementById('extensionChips'),
      daysChips: document.getElementById('daysChips'),
      logRecordModal: document.getElementById('logRecordModal'),
      logRecordModalTitle: document.getElementById('logRecordModalTitle'),
      logRecordModalBody: document.getElementById('logRecordModalBody'),
      closeLogRecordModal: document.getElementById('closeLogRecordModal'),
    };

    this._bindEvents();
    this._syncResponsiveState();
    this._setupHudLogo();
    this.loadFolders();
  }

  _setupHudLogo() {
    const container = document.getElementById('logsHudLogo');
    if (!container || container.querySelector('svg.hud-svg')) return;

    fetch('/assets/jarvis-hud-logo.svg', { cache: 'no-cache' })
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.text();
      })
      .then((svgMarkup) => {
        container.insertAdjacentHTML('beforeend', svgMarkup.replace(/<\?xml[^?]*\?>\s*/i, ''));
        const svg = container.querySelector('svg');
        if (svg) {
          svg.classList.add('hud-svg', 'online');
          svg.classList.remove('offline');
        }
      })
      .catch((err) => console.warn('[Logs] HUD logo load failed:', err));
  }

  _bindEvents() {
    this.elements.refreshFoldersBtn.addEventListener('click', () => this.loadFolders(true));

    this.elements.folderFilterInput.addEventListener('input', Utils.debounce((event) => {
      this.state.folderFilter = event.target.value.trim().toLowerCase();
      this.renderFolders();
    }, 120));

    this.elements.fileSearchInput.addEventListener('input', Utils.debounce((event) => {
      this.state.fileSearch = event.target.value.trim();
      this.loadFiles(true);
    }, 220));

    this.elements.sortSelect.addEventListener('change', (event) => {
      this.state.sort = event.target.value;
      this.loadFiles(true);
    });

    this.elements.loadMoreFilesBtn.addEventListener('click', () => this.loadFiles(false));
    this.elements.loadMoreContentBtn.addEventListener('click', () => this.loadContent(false));
    this.elements.refreshContentBtn.addEventListener('click', () => this.refreshCurrentContent());
    this.elements.backToFoldersBtn.addEventListener('click', () => this.setMobileStage('folders'));
    this.elements.backToFilesBtn.addEventListener('click', () => this.setMobileStage('files'));
    this.elements.selectedFileLabelBtn.addEventListener('click', () => this.openCurrentFileModal());
    this.elements.closeLogRecordModal.addEventListener('click', () => this.closeRecordModal());
    this.elements.logRecordModal.addEventListener('click', (event) => {
      if (event.target.dataset.closeModal === 'true') {
        this.closeRecordModal();
      }
    });

    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') {
        this.closeRecordModal();
      }
    });

    window.addEventListener('resize', Utils.debounce(() => this._syncResponsiveState(), 120));

    this.elements.extensionChips.querySelectorAll('.filter-chip').forEach((chip) => {
      chip.addEventListener('click', () => {
        this._setActiveChip(this.elements.extensionChips, chip);
        this.state.extension = chip.dataset.extension || '';
        this.loadFiles(true);
      });
    });

    this.elements.daysChips.querySelectorAll('.filter-chip').forEach((chip) => {
      chip.addEventListener('click', () => {
        this._setActiveChip(this.elements.daysChips, chip);
        this.state.days = chip.dataset.days || '';
        this.loadFiles(true);
      });
    });
  }

  async loadFolders(preserveSelection = false) {
    try {
      const response = await Utils.auth.fetch('/api/logs/folders');
      const data = await response.json();
      this.state.folders = data.folders || [];
      this.renderFolders();

      if (!this.state.folders.length) {
        this.state.selectedFolder = '';
        this.renderFiles();
        return;
      }

      const selectedStillExists = this.state.folders.some((folder) => folder.path === this.state.selectedFolder);
      if (!preserveSelection || !selectedStillExists) {
        this.selectFolder(this.state.folders[0].path, true);
      } else {
        this.renderFolders();
        this.loadFiles(true);
      }
    } catch (error) {
      console.error('[LogsViewer] Failed to load folders:', error);
      this.elements.folderList.innerHTML = '<div class="empty-state compact">Failed to load folders.</div>';
      Utils.toast('Failed to load folders', 'error');
    }
  }

  renderFolders() {
    const filtered = this.state.folders.filter((folder) => {
      if (!this.state.folderFilter) {
        return true;
      }
      const haystack = `${folder.label} ${(folder.extensions || []).join(' ')}`.toLowerCase();
      return haystack.includes(this.state.folderFilter);
    });

    if (!filtered.length) {
      this.elements.folderList.innerHTML = '<div class="empty-state compact">No matching folders.</div>';
      return;
    }

    this.elements.folderList.innerHTML = filtered.map((folder) => `
      <button class="folder-card ${folder.path === this.state.selectedFolder ? 'active' : ''}" data-folder="${Utils.escapeHtml(folder.path)}">
        <div class="folder-card-header">
          <h3>${Utils.escapeHtml(folder.label)}</h3>
          <span class="meta-pill">${folder.file_count} files</span>
        </div>
        <div class="folder-card-meta">
          ${(folder.extensions || []).map((extension) => `<span class="tag-pill">${Utils.escapeHtml(extension)}</span>`).join('')}
        </div>
        <div class="folder-card-meta">
          <span>${this.formatDateTime(folder.latest_modified_at)}</span>
          <span>${Utils.escapeHtml(folder.latest_file || '')}</span>
        </div>
      </button>
    `).join('');

    this.elements.folderList.querySelectorAll('.folder-card').forEach((button) => {
      button.addEventListener('click', () => this.selectFolder(button.dataset.folder || ''));
    });
  }

  async selectFolder(folderPath, force = false) {
    if (!force && folderPath === this.state.selectedFolder) {
      return;
    }
    this.state.selectedFolder = folderPath;
    this.state.selectedFile = '';
    this.state.fileOffset = 0;
    this.state.contentOffset = 0;
    this.state.contentPath = '';
    this.state.contentRecords = [];
    this.state.contentLines = [];
    this.state.markdownContent = '';
    this.renderFolders();
    if (this.isMobileLayout()) {
      this.setMobileStage('files');
    }
    await this.loadFiles(true);
  }

  async loadFiles(reset = true) {
    if (!this.state.selectedFolder && this.state.selectedFolder !== '') {
      return;
    }

    if (reset) {
      this.state.fileOffset = 0;
      this.state.files = [];
      this.state.hasMoreFiles = false;
      this.elements.fileList.innerHTML = '<div class="empty-state compact">Loading files...</div>';
      this.renderContent();
    }

    const params = new URLSearchParams({
      folder: this.state.selectedFolder,
      search: this.state.fileSearch,
      extension: this.state.extension,
      sort: this.state.sort,
      offset: String(this.state.fileOffset),
      limit: '50',
    });
    if (this.state.days) {
      params.set('days', this.state.days);
    }

    try {
      const response = await Utils.auth.fetch(`/api/logs/files?${params.toString()}`);
      const data = await response.json();
      const newFiles = data.files || [];

      this.state.files = reset ? newFiles : this.state.files.concat(newFiles);
      this.state.fileOffset = data.next_offset || this.state.files.length;
      this.state.hasMoreFiles = Boolean(data.has_more);

      const folderLabel = this.state.selectedFolder || 'logs';
      this.elements.selectedFolderLabel.textContent = folderLabel;
      this.elements.fileSummary.textContent = `${data.total || 0} file${(data.total || 0) === 1 ? '' : 's'}`;
      this.renderFiles();

      const selectedStillExists = this.state.files.some((file) => file.path === this.state.selectedFile);
      if (this.isMobileLayout()) {
        if (!selectedStillExists) {
          this.state.selectedFile = '';
          this.state.contentPath = '';
        }
        this.renderContent();
      } else if (!selectedStillExists && this.state.files.length) {
        await this.selectFile(this.state.files[0].path);
      } else {
        this.renderContent();
      }
    } catch (error) {
      console.error('[LogsViewer] Failed to load files:', error);
      this.elements.fileList.innerHTML = '<div class="empty-state compact">Failed to load files.</div>';
      Utils.toast('Failed to load files', 'error');
    }
  }

  renderFiles() {
    if (!this.state.files.length) {
      this.elements.fileList.innerHTML = '<div class="empty-state compact">No files matched this folder/filter.</div>';
      this.elements.loadMoreFilesBtn.hidden = true;
      return;
    }

    this.elements.fileList.innerHTML = this.state.files.map((file) => `
      <button class="file-card ${file.path === this.state.selectedFile ? 'active' : ''}" data-path="${Utils.escapeHtml(file.path)}">
        <div class="file-card-header">
          <h3>${Utils.escapeHtml(file.filename)}</h3>
          <span class="meta-pill">${Utils.escapeHtml(file.size_label)}</span>
        </div>
        <div class="file-card-meta">
          <span>${this.formatDateTime(file.modified_at)}</span>
          <span>${Utils.escapeHtml(file.extension)}</span>
          ${file.search_hit_count ? `<span>${file.search_hit_count} matches</span>` : ''}
        </div>
        <div class="file-card-meta">
          ${(file.tags || []).map((tag) => `<span class="tag-pill">${Utils.escapeHtml(tag)}</span>`).join('')}
        </div>
      </button>
    `).join('');

    this.elements.fileList.querySelectorAll('.file-card').forEach((button) => {
      button.addEventListener('click', () => this.selectFile(button.dataset.path || ''));
    });

    this.elements.loadMoreFilesBtn.hidden = !this.state.hasMoreFiles;
  }

  async selectFile(filePath) {
    if (!filePath) {
      return;
    }
    if (filePath === this.state.selectedFile) {
      await this.refreshCurrentContent();
      return;
    }
    this.state.selectedFile = filePath;
    this.state.contentPath = filePath;
    this.state.contentOffset = 0;
    this.state.contentViewType = '';
    this.state.contentRecords = [];
    this.state.contentLines = [];
    this.state.markdownContent = '';
    this.renderFiles();
    if (this.isMobileLayout()) {
      this.setMobileStage('viewer');
    }
    await this.loadContent(true);
  }

  async refreshCurrentContent() {
    if (!this.state.contentPath) {
      return;
    }
    this.elements.refreshContentBtn.disabled = true;
    this.elements.refreshContentBtn.classList.add('is-refreshing');
    try {
      await this.loadContent(true);
      Utils.toast('Log refreshed', 'success', 1400);
    } finally {
      this.elements.refreshContentBtn.classList.remove('is-refreshing');
      this.elements.refreshContentBtn.disabled = !this.state.contentPath;
    }
  }

  async loadContent(reset = true) {
    if (!this.state.contentPath) {
      this.renderContent();
      return;
    }

    if (reset) {
      this.state.contentOffset = 0;
      this.elements.viewerContent.innerHTML = '<div class="empty-state compact">Loading file...</div>';
    }

    const params = new URLSearchParams({
      path: this.state.contentPath,
      offset: String(this.state.contentOffset),
      limit: '120',
    });
    if (this.state.fileSearch) {
      params.set('search', this.state.fileSearch);
    }

    try {
      const response = await Utils.auth.fetch(`/api/logs/content?${params.toString()}`);
      const data = await response.json();

      this.state.contentViewType = data.view_type || '';
      this.state.contentOffset = data.next_offset || this.state.contentOffset;
      this.state.hasMoreContent = Boolean(data.has_more);
      this.elements.selectedFileLabel.textContent = data.filename || this.state.contentPath;
      this.elements.viewerSummary.textContent = this.buildViewerSummary(data);

      if (data.view_type === 'yaml-records') {
        const incoming = data.records || [];
        this.state.contentRecords = reset ? incoming : this.state.contentRecords.concat(incoming);
      } else if (data.view_type === 'text-lines') {
        const incoming = data.lines || [];
        this.state.contentLines = reset ? incoming : this.state.contentLines.concat(incoming);
      } else if (data.view_type === 'markdown') {
        this.state.markdownContent = data.content || '';
      }

      this.renderContent();
      this.updateViewerTitleAction();
    } catch (error) {
      console.error('[LogsViewer] Failed to load content:', error);
      this.elements.viewerContent.innerHTML = '<div class="empty-state compact">Failed to load file.</div>';
      Utils.toast('Failed to load selected file', 'error');
    }
  }

  renderContent() {
    if (!this.state.contentPath) {
      this.elements.viewerContent.innerHTML = `
        <div class="empty-state">
          <p>Pick a file to open it in a cleaner read-only view.</p>
          <p>Newest records load first so you can start with the useful part.</p>
        </div>
      `;
      this.elements.loadMoreContentBtn.hidden = true;
      this.updateViewerTitleAction();
      return;
    }

    if (this.state.contentViewType === 'yaml-records') {
      if (!this.state.contentRecords.length) {
        this.elements.viewerContent.innerHTML = `<div class="empty-state compact">${
          this.state.fileSearch ? 'No matching JSONL records in this file.' : 'No JSONL records found.'
        }</div>`;
      } else {
        this.elements.viewerContent.innerHTML = this.state.contentRecords.map((record, index) => `
          <article class="record-card">
            <div class="record-header">
              <button class="record-open-btn" data-record-index="${index}">
                ${this.escapeAndHighlight(record.timestamp || `Entry ${index + 1}`)}
              </button>
              <span>YAML</span>
            </div>
            <div class="record-body yaml-pretty">${this.renderYamlMarkup(record.yaml || '')}</div>
          </article>
        `).join('');

        this.elements.viewerContent.querySelectorAll('.record-open-btn').forEach((button) => {
          button.addEventListener('click', () => {
            const index = Number(button.dataset.recordIndex || '0');
            const record = this.state.contentRecords[index];
            if (record) {
              this.openRecordModal(record);
            }
          });
        });
      }
    } else if (this.state.contentViewType === 'text-lines') {
      if (!(this.state.contentLines || []).length) {
        this.elements.viewerContent.innerHTML = `<div class="empty-state compact">${
          this.state.fileSearch ? 'No matching log lines in this file.' : 'No log lines found.'
        }</div>`;
      } else {
        this.elements.viewerContent.innerHTML = `
          <pre class="log-lines">${this.highlightText(Utils.escapeHtml((this.state.contentLines || []).join('\n')))}</pre>
        `;
      }
    } else if (this.state.contentViewType === 'markdown') {
      this.elements.viewerContent.innerHTML = `<div class="markdown-viewer">${Utils.parseMarkdown(this.state.markdownContent || '')}</div>`;
      Utils.hydrateRichContent(this.elements.viewerContent);
      this.applyDomHighlights(this.elements.viewerContent);
    } else {
      this.elements.viewerContent.innerHTML = '<div class="empty-state compact">Nothing to show yet.</div>';
    }

    this.elements.loadMoreContentBtn.hidden = !this.state.hasMoreContent;
    this.updateViewerTitleAction();
  }

  buildViewerSummary(data) {
    const base = `${data.extension || ''} • ${data.size_label || ''} • ${this.formatDateTime(data.modified_at)}`;
    if (data.view_type === 'yaml-records') {
      return data.search
        ? `${base} • filtered to matching records`
        : `${base} • dotted keys nested into YAML`;
    }
    if (data.view_type === 'text-lines') {
      return data.search
        ? `${base} • filtered to matching lines`
        : `${base} • newest lines first`;
    }
    return base;
  }

  formatDateTime(value) {
    if (!value) {
      return 'Unknown time';
    }
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return value;
    }
    return date.toLocaleString([], {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  }

  _setActiveChip(container, activeChip) {
    container.querySelectorAll('.filter-chip').forEach((chip) => chip.classList.remove('active'));
    activeChip.classList.add('active');
  }

  updateViewerTitleAction() {
    const isMarkdown = this.state.contentViewType === 'markdown' && !!this.state.contentPath;
    this.elements.selectedFileLabelBtn.disabled = !isMarkdown;
    this.elements.selectedFileLabelBtn.classList.toggle('is-clickable', isMarkdown);
    this.elements.refreshContentBtn.disabled = !this.state.contentPath;
  }

  openCurrentFileModal() {
    if (!this.state.contentPath || this.state.contentViewType !== 'markdown') {
      return;
    }
    this.openModal({
      title: this.elements.selectedFileLabel.textContent || 'Markdown file',
      contentType: 'markdown',
      content: this.state.markdownContent || '',
    });
  }

  isMobileLayout() {
    return window.innerWidth <= 768;
  }

  setMobileStage(stage) {
    this.state.mobileStage = stage;
    document.body.dataset.logsStage = stage;
  }

  _syncResponsiveState() {
    if (this.isMobileLayout()) {
      if (this.state.selectedFile) {
        this.setMobileStage('viewer');
      } else if (this.state.selectedFolder) {
        this.setMobileStage('files');
      } else {
        this.setMobileStage('folders');
      }
    } else {
      document.body.dataset.logsStage = 'desktop';
    }
  }

  openRecordModal(record) {
    this.openModal({
      title: record.timestamp || 'Log record',
      contentType: 'yaml',
      content: record.yaml || '',
    });
  }

  closeRecordModal() {
    this.elements.logRecordModal.hidden = true;
    this.elements.logRecordModalBody.innerHTML = '';
    document.body.style.overflow = this.isMobileLayout() ? 'auto' : '';
  }

  openModal({ title, contentType, content }) {
    this.elements.logRecordModalTitle.textContent = title || 'Viewer';

    if (contentType === 'markdown') {
      this.elements.logRecordModalBody.innerHTML = `<div class="markdown-viewer modal-record-body">${Utils.parseMarkdown(content || '')}</div>`;
      Utils.hydrateRichContent(this.elements.logRecordModalBody);
      this.applyDomHighlights(this.elements.logRecordModalBody);
    } else if (contentType === 'yaml') {
      this.elements.logRecordModalBody.innerHTML = `<div class="record-body modal-record-body yaml-pretty">${this.renderYamlMarkup(content || '')}</div>`;
    } else {
      this.elements.logRecordModalBody.innerHTML = `<pre class="record-body modal-record-body">${this.highlightText(Utils.escapeHtml(content || ''))}</pre>`;
    }

    this.elements.logRecordModal.hidden = false;
    document.body.style.overflow = 'hidden';
  }

  highlightText(htmlText) {
    const query = (this.state.fileSearch || '').trim();
    if (!query) {
      return htmlText;
    }
    const escapedQuery = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const regex = new RegExp(escapedQuery, 'gi');
    return htmlText.replace(regex, (match) => `<mark class="log-highlight">${match}</mark>`);
  }

  escapeAndHighlight(text) {
    return this.highlightText(Utils.escapeHtml(text || ''));
  }

  renderYamlMarkup(yamlText) {
    return String(yamlText || '')
      .split('\n')
      .map((line) => this.renderYamlLine(line))
      .join('');
  }

  renderYamlLine(line) {
    if (!line) {
      return '<div class="yaml-line yaml-line-empty">&nbsp;</div>';
    }

    const indentMatch = line.match(/^(\s*)/);
    const indent = indentMatch ? indentMatch[1] : '';
    const trimmed = line.slice(indent.length);
    const indentHtml = indent ? `<span class="yaml-indent">${'&nbsp;'.repeat(indent.length)}</span>` : '';

    if (!trimmed) {
      return `<div class="yaml-line">${indentHtml}</div>`;
    }

    const listMatch = trimmed.match(/^-\s+(.*)$/);
    if (listMatch) {
      return `<div class="yaml-line">${indentHtml}<span class="yaml-bullet">-</span> ${this.renderYamlContent(listMatch[1])}</div>`;
    }

    return `<div class="yaml-line">${indentHtml}${this.renderYamlContent(trimmed)}</div>`;
  }

  renderYamlContent(content) {
    const keyValueMatch = content.match(/^([^:]+):(.*)$/);
    if (!keyValueMatch) {
      return this.renderRichInlineText(content, 'yaml-text');
    }

    const key = keyValueMatch[1];
    const remainder = keyValueMatch[2] || '';
    const value = remainder.startsWith(' ') ? remainder.slice(1) : remainder;

    if (!value) {
      return `<span class="yaml-key">${this.escapeAndHighlight(key)}</span><span class="yaml-colon">:</span>`;
    }

    return [
      `<span class="yaml-key">${this.escapeAndHighlight(key)}</span>`,
      `<span class="yaml-colon">:</span> `,
      this.renderYamlValue(value),
    ].join('');
  }

  renderYamlValue(value) {
    const trimmed = value.trim();
    if (!trimmed) {
      return '<span class="yaml-text"></span>';
    }

    if (trimmed === 'null') {
      return `<span class="yaml-null">${this.escapeAndHighlight(value)}</span>`;
    }

    if (trimmed === 'true' || trimmed === 'false') {
      return `<span class="yaml-bool">${this.escapeAndHighlight(value)}</span>`;
    }

    if (/^-?\d+(\.\d+)?$/.test(trimmed)) {
      return `<span class="yaml-number">${this.escapeAndHighlight(value)}</span>`;
    }

    if (trimmed === '|'
      || trimmed === '>'
      || trimmed === '|-'
      || trimmed === '>-'
      || trimmed === '|+'
      || trimmed === '>+') {
      return `<span class="yaml-operator">${this.escapeAndHighlight(value)}</span>`;
    }

    if ((trimmed.startsWith("'") && trimmed.endsWith("'")) || (trimmed.startsWith('"') && trimmed.endsWith('"'))) {
      return this.renderRichInlineText(value, 'yaml-string');
    }

    return this.renderRichInlineText(value, 'yaml-string');
  }

  renderRichInlineText(text, defaultClass = 'yaml-text') {
    const source = String(text || '');
    const tokenRegex = /((?:stash:\/\/|https?:\/\/)[^\s'"`]+|\b[\w./:-]+\.(?:jpg|jpeg|png|gif|webp|svg|md|jsonl|log)\b)/gi;
    let output = '';
    let lastIndex = 0;
    let match;

    while ((match = tokenRegex.exec(source)) !== null) {
      output += this.wrapYamlSegment(source.slice(lastIndex, match.index), defaultClass);
      output += this.wrapYamlSegment(match[0], this.getYamlTokenClass(match[0]));
      lastIndex = match.index + match[0].length;
    }

    output += this.wrapYamlSegment(source.slice(lastIndex), defaultClass);
    return output;
  }

  wrapYamlSegment(text, className) {
    if (!text) {
      return '';
    }
    return `<span class="${className}">${this.escapeAndHighlight(text)}</span>`;
  }

  getYamlTokenClass(token) {
    if (/\.(jpg|jpeg|png|gif|webp|svg)$/i.test(token)) {
      return 'yaml-image-ref';
    }
    return 'yaml-linklike';
  }

  applyDomHighlights(container) {
    const query = (this.state.fileSearch || '').trim();
    if (!query || !container) {
      return;
    }

    const regex = new RegExp(query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi');
    const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT, {
      acceptNode: (node) => {
        if (!node.nodeValue || !node.nodeValue.trim()) {
          return NodeFilter.FILTER_REJECT;
        }
        const parentTag = node.parentElement?.tagName;
        if (parentTag === 'SCRIPT' || parentTag === 'STYLE') {
          return NodeFilter.FILTER_REJECT;
        }
        regex.lastIndex = 0;
        return regex.test(node.nodeValue) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
      }
    });

    const textNodes = [];
    while (walker.nextNode()) {
      textNodes.push(walker.currentNode);
    }

    textNodes.forEach((node) => {
      const text = node.nodeValue;
      if (!text) {
        return;
      }
      regex.lastIndex = 0;
      const fragment = document.createDocumentFragment();
      let lastIndex = 0;
      let match;
      while ((match = regex.exec(text)) !== null) {
        fragment.appendChild(document.createTextNode(text.slice(lastIndex, match.index)));
        const mark = document.createElement('mark');
        mark.className = 'log-highlight';
        mark.textContent = match[0];
        fragment.appendChild(mark);
        lastIndex = match.index + match[0].length;
      }
      fragment.appendChild(document.createTextNode(text.slice(lastIndex)));
      node.parentNode.replaceChild(fragment, node);
    });
  }
}

document.addEventListener('DOMContentLoaded', () => {
  window.logsViewerApp = new LogsViewerApp();
});
