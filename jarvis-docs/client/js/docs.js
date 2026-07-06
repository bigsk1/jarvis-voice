class DocsApp {
  constructor() {
    this.state = {
      folders: [],
      selectedFolder: '',
      documents: [],
      selectedDocument: '',
      selectedDocumentData: null,
      search: '',
      sort: 'recent',
      offset: 0,
      hasMore: false,
      editEnabled: false,
      isEditing: false,
      libraryOpen:
        typeof window.matchMedia !== 'undefined'
          ? window.matchMedia('(min-width: 1200px)').matches
          : true,
      outlineOpen:
        typeof window.matchMedia !== 'undefined'
          ? window.matchMedia('(min-width: 1500px)').matches
          : true,
    };

    this.elements = {
      docsLayout: document.querySelector('.docs-layout'),
      docsBackdrop: document.getElementById('docsBackdrop'),
      globalSearchInput: document.getElementById('globalSearchInput'),
      sortSelect: document.getElementById('sortSelect'),
      toggleLibraryBtn: document.getElementById('toggleLibraryBtn'),
      toggleOutlineBtn: document.getElementById('toggleOutlineBtn'),
      closeLibraryBtn: document.getElementById('closeLibraryBtn'),
      closeOutlineBtn: document.getElementById('closeOutlineBtn'),
      folderRail: document.getElementById('folderRail'),
      libraryCount: document.getElementById('libraryCount'),
      activeFolderLabel: document.getElementById('activeFolderLabel'),
      documentFeed: document.getElementById('documentFeed'),
      loadMoreBtn: document.getElementById('loadMoreBtn'),
      emptyReader: document.getElementById('emptyReader'),
      readerView: document.getElementById('readerView'),
      renderedMarkdown: document.getElementById('renderedMarkdown'),
      editorView: document.getElementById('editorView'),
      editorTextarea: document.getElementById('editorTextarea'),
      docPath: document.getElementById('docPath'),
      docMeta: document.getElementById('docMeta'),
      refreshDocBtn: document.getElementById('refreshDocBtn'),
      editDocBtn: document.getElementById('editDocBtn'),
      cancelEditBtn: document.getElementById('cancelEditBtn'),
      saveEditBtn: document.getElementById('saveEditBtn'),
      insightCards: document.getElementById('insightCards'),
      outlineNav: document.getElementById('outlineNav'),
      toastContainer: document.getElementById('toastContainer'),
    };

    this._bindEvents();
    this.restoreSidebarState();
    window.addEventListener('resize', this.debounce(() => this.handleResize(), 120));
    if (typeof window.matchMedia === 'function') {
      this._compactMql = window.matchMedia('(max-width: 1199px)');
      this._onCompactChange = () => {
        this.handleResize();
      };
      this._compactMql.addEventListener('change', this._onCompactChange);
    }
    this.loadInitial();
  }

  _bindEvents() {
    this.elements.globalSearchInput.addEventListener('input', this.debounce((event) => {
      this.state.search = event.target.value.trim();
      this.loadDocuments(true);
    }, 220));

    this.elements.sortSelect.addEventListener('change', (event) => {
      this.state.sort = event.target.value;
      this.loadDocuments(true);
    });

    this.elements.loadMoreBtn.addEventListener('click', () => this.loadDocuments(false));
    this.elements.refreshDocBtn.addEventListener('click', () => this.refreshDocument());
    this.elements.editDocBtn.addEventListener('click', () => this.enterEditMode());
    this.elements.cancelEditBtn.addEventListener('click', () => this.exitEditMode());
    this.elements.saveEditBtn.addEventListener('click', () => this.saveDocument());
    this.elements.toggleLibraryBtn.addEventListener('click', () => this.toggleSidebar('library'));
    this.elements.toggleOutlineBtn.addEventListener('click', () => this.toggleSidebar('outline'));
    this.elements.closeLibraryBtn.addEventListener('click', () => this.setSidebar('library', false));
    this.elements.closeOutlineBtn.addEventListener('click', () => this.setSidebar('outline', false));

    if (this.elements.docsBackdrop) {
      this.elements.docsBackdrop.addEventListener('click', () => {
        if (!this.isCompactLayout()) {
          return;
        }
        this.setSidebar('library', false);
        this.setSidebar('outline', false);
      });
    }

    document.addEventListener('keydown', (event) => {
      if (event.key !== 'Escape') {
        return;
      }
      if (!this.isCompactLayout()) {
        return;
      }
      if (!this.state.libraryOpen && !this.state.outlineOpen) {
        return;
      }
      event.preventDefault();
      this.setSidebar('library', false);
      this.setSidebar('outline', false);
    });
  }

  async loadInitial() {
    try {
      await this.loadConfig();
      await this.loadFolders();
      await this.loadDocuments(true);

      const deepLinkedPath = new URLSearchParams(window.location.search).get('path');
      if (deepLinkedPath) {
        await this.selectDocument(deepLinkedPath);
      } else if (this.state.documents.length > 0) {
        await this.selectDocument(this.state.documents[0].path);
      }
    } catch (error) {
      console.error('[DocsApp] Initial load failed:', error);
      this.toast(error.message || 'Failed to load docs', 'error');
    }
  }

  async loadConfig() {
    const response = await this.authFetch('/api/docs/config');
    const data = await response.json();
    this.state.editEnabled = Boolean(data.edit_enabled);
  }

  async loadFolders() {
    const response = await this.authFetch('/api/docs/folders');
    const data = await response.json();
    this.state.folders = data.folders || [];
    this.renderFolders();
  }

  async loadDocuments(reset = true) {
    if (reset) {
      this.state.offset = 0;
      this.state.documents = [];
      this.elements.documentFeed.innerHTML = '<div class="loading-card">Loading documents…</div>';
    }

    const params = new URLSearchParams({
      folder: this.state.selectedFolder,
      search: this.state.search,
      sort: this.state.sort,
      offset: String(this.state.offset),
      limit: '40',
    });

    const response = await this.authFetch(`/api/docs/documents?${params.toString()}`);
    const data = await response.json();
    const incoming = data.documents || [];
    this.state.documents = reset ? incoming : this.state.documents.concat(incoming);
    this.state.offset = data.next_offset || this.state.documents.length;
    this.state.hasMore = Boolean(data.has_more);

    this.elements.libraryCount.textContent = `${data.total || 0} doc${(data.total || 0) === 1 ? '' : 's'}`;
    this.elements.activeFolderLabel.textContent = this.folderLabel(this.state.selectedFolder);
    this.renderDocuments();

    if (
      this.state.selectedDocument
      && !this.state.documents.some((document) => document.path === this.state.selectedDocument)
    ) {
      this.state.selectedDocument = '';
      this.state.selectedDocumentData = null;
      this.renderReaderEmpty();
    }
  }

  async selectFolder(folderPath) {
    this.state.selectedFolder = folderPath;
    this.renderFolders();
    await this.loadDocuments(true);
  }

  async selectDocument(relativePath) {
    if (!relativePath) {
      return false;
    }

    try {
      const response = await this.authFetch(`/api/docs/document?path=${encodeURIComponent(relativePath)}`);
      const data = await response.json();
      this.state.selectedDocument = relativePath;
      this.state.selectedDocumentData = data;
      this.state.isEditing = false;
      this.renderDocuments();
      this.renderDocument(data);
      this.syncUrl(relativePath);
      if (this.isCompactLayout()) {
        this.setSidebar('library', false);
      }
      return true;
    } catch (error) {
      console.error('[DocsApp] Open document failed:', error);
      this.toast(error.message || 'Failed to open document', 'error');
      return false;
    }
  }

  async refreshDocument() {
    if (!this.state.selectedDocument) {
      return;
    }
    const ok = await this.selectDocument(this.state.selectedDocument);
    if (ok) {
      this.toast('Document refreshed', 'success');
    }
  }

  enterEditMode() {
    if (!this.state.editEnabled || !this.state.selectedDocumentData) {
      return;
    }
    this.state.isEditing = true;
    this.elements.editorTextarea.value = this.state.selectedDocumentData.content || '';
    this.renderEditState();
  }

  exitEditMode() {
    this.state.isEditing = false;
    this.renderEditState();
  }

  async saveDocument() {
    if (!this.state.selectedDocument) {
      return;
    }

    this.elements.saveEditBtn.disabled = true;
    try {
      const response = await this.authFetch(`/api/docs/document?path=${encodeURIComponent(this.state.selectedDocument)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: this.elements.editorTextarea.value }),
      });
      const data = await response.json();
      this.state.selectedDocumentData = data;
      this.state.isEditing = false;
      this.renderDocument(data);
      await this.loadDocuments(true);
      this.toast('Document saved', 'success');
    } catch (error) {
      console.error('[DocsApp] Save failed:', error);
      this.toast(error.message || 'Failed to save document', 'error');
    } finally {
      this.elements.saveEditBtn.disabled = false;
    }
  }

  renderFolders() {
    if (!this.state.folders.length) {
      this.elements.folderRail.innerHTML = '<div class="loading-card">No markdown folders found.</div>';
      return;
    }

    this.elements.folderRail.innerHTML = this.state.folders.map((folder) => `
      <button class="folder-chip ${folder.path === this.state.selectedFolder ? 'active' : ''}" data-folder="${this.escapeHtml(folder.path)}">
        <div class="folder-chip-title">${this.escapeHtml(folder.label)}</div>
        <div class="folder-chip-meta">${folder.document_count} docs</div>
        <div class="folder-chip-meta">${this.formatDate(folder.latest_modified_at)} · ${this.escapeHtml(folder.latest_document || '')}</div>
      </button>
    `).join('');

    this.elements.folderRail.querySelectorAll('.folder-chip').forEach((button) => {
      button.addEventListener('click', () => this.selectFolder(button.dataset.folder || ''));
    });
  }

  renderDocuments() {
    if (!this.state.documents.length) {
      this.elements.documentFeed.innerHTML = '<div class="loading-card">No documents matched this section or search.</div>';
      this.elements.loadMoreBtn.hidden = true;
      return;
    }

    this.elements.documentFeed.innerHTML = this.state.documents.map((document) => `
      <article class="doc-card ${document.path === this.state.selectedDocument ? 'active' : ''}" data-path="${this.escapeHtml(document.path)}">
        <div class="doc-card-title-row">
          <div class="doc-card-title">${this.escapeHtml(document.title)}</div>
        </div>
        <div class="doc-card-meta">
          <span>${this.escapeHtml(document.folder || 'docs')}</span>
          <span>${document.word_count} words</span>
          <span>${this.formatDate(document.modified_at)}</span>
        </div>
      </article>
    `).join('');

    this.elements.documentFeed.querySelectorAll('.doc-card').forEach((card) => {
      card.addEventListener('click', () => this.selectDocument(card.dataset.path || ''));
    });

    this.elements.loadMoreBtn.hidden = !this.state.hasMore;
  }

  renderDocument(documentData) {
    this.elements.emptyReader.hidden = true;
    this.elements.readerView.hidden = false;
    this.elements.docPath.textContent = documentData.path || '';
    this.elements.docMeta.textContent = `${documentData.word_count} words · ${documentData.reading_time_minutes} min read · ${this.formatDate(documentData.modified_at)}`;
    this.elements.refreshDocBtn.disabled = false;

    if (this.state.editEnabled) {
      this.elements.editDocBtn.hidden = false;
    }

    this.elements.renderedMarkdown.innerHTML = this.parseMarkdown(documentData.content || '', documentData.path || '');
    void this.decorateMarkdown(documentData.path || '');
    this.renderInsights(documentData);
    this.renderOutline(documentData.outline || []);
    this.renderEditState();
  }

  renderReaderEmpty() {
    this.state.selectedDocumentData = null;
    this.elements.emptyReader.hidden = false;
    this.elements.readerView.hidden = true;
    this.elements.editorView.hidden = true;
    this.elements.refreshDocBtn.disabled = true;
    this.elements.editDocBtn.hidden = true;
    this.elements.docPath.textContent = 'Select a document';
    this.elements.docMeta.textContent = 'Markdown rendering, reader layout, and optional in-place editing.';
    this.elements.insightCards.innerHTML = `
      <div class="insight-card muted">
        <span class="insight-label">Status</span>
        <strong>Waiting</strong>
        <p>Document stats and headings show up here once you open a file.</p>
      </div>
    `;
    this.elements.outlineNav.innerHTML = '<div class="outline-empty">Open a markdown file to jump by heading.</div>';
  }

  renderEditState() {
    const editing = this.state.isEditing && this.state.selectedDocumentData;
    this.elements.editorView.hidden = !editing;
    this.elements.readerView.hidden = editing || !this.state.selectedDocumentData;
    this.elements.editDocBtn.textContent = editing ? 'Editing' : 'Edit';
    this.elements.editDocBtn.disabled = editing;
  }

  renderInsights(documentData) {
    const title = this.escapeHtml(documentData.title || documentData.filename || 'Document');
    const folder = this.escapeHtml(documentData.folder || 'docs');
    const tags = (documentData.tags || []).slice(0, 4).map((tag) => `<span class="tag">${this.escapeHtml(tag)}</span>`).join('');
    this.elements.insightCards.innerHTML = `
      <div class="insight-card">
        <span class="insight-label">Document</span>
        <strong>${title}</strong>
        <p>${folder}</p>
      </div>
      <div class="insight-card">
        <span class="insight-label">Reading</span>
        <strong>${documentData.reading_time_minutes} min</strong>
        <p>${documentData.word_count} words · ${documentData.size_label}</p>
      </div>
      <div class="insight-card">
        <span class="insight-label">Updated</span>
        <strong>${this.formatDate(documentData.modified_at)}</strong>
        <p>${tags || 'No tags inferred yet.'}</p>
      </div>
    `;
  }

  renderOutline(outline) {
    if (!outline.length) {
      this.elements.outlineNav.innerHTML = '<div class="outline-empty">No headings found in this file.</div>';
      return;
    }

    this.elements.outlineNav.innerHTML = outline.map((item) => {
      const anchorId = this.slugify(item.title);
      return `
        <a class="outline-link level-${Math.min(item.level, 6)}" href="#${encodeURIComponent(anchorId)}" data-anchor="${this.escapeHtml(anchorId)}">
          ${this.escapeHtml(item.title)}
        </a>
      `;
    }).join('');

    this.elements.outlineNav.querySelectorAll('.outline-link').forEach((link) => {
      link.addEventListener('click', (event) => {
        event.preventDefault();
        const anchor = link.dataset.anchor || '';
        const target = document.getElementById(anchor);
        if (target) {
          target.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
        if (this.isCompactLayout()) {
          this.setSidebar('outline', false);
        }
      });
    });
  }

  restoreSidebarState() {
    const saved = this.storageGet('docs_sidebar_state', {});
    if (typeof saved.libraryOpen === 'boolean') {
      this.state.libraryOpen = saved.libraryOpen;
    }
    if (typeof saved.outlineOpen === 'boolean') {
      this.state.outlineOpen = saved.outlineOpen;
    }
    this.handleResize();
  }

  handleResize() {
    this.applySidebarState();
  }

  isCompactLayout() {
    if (typeof window.matchMedia === 'function') {
      return window.matchMedia('(max-width: 1199px)').matches;
    }
    return window.innerWidth <= 1199;
  }

  applyBackdropState() {
    const backdrop = this.elements.docsBackdrop;
    if (!backdrop) {
      return;
    }
    const compact = this.isCompactLayout();
    if (!compact) {
      backdrop.hidden = true;
      backdrop.classList.remove('is-visible');
      return;
    }
    const show = this.state.libraryOpen || this.state.outlineOpen;
    if (!show) {
      backdrop.hidden = true;
      backdrop.classList.remove('is-visible');
      return;
    }
    backdrop.hidden = false;
    backdrop.classList.add('is-visible');
  }

  toggleSidebar(sidebar) {
    if (sidebar === 'library') {
      this.setSidebar('library', !this.state.libraryOpen);
      return;
    }
    this.setSidebar('outline', !this.state.outlineOpen);
  }

  setSidebar(sidebar, isOpen) {
    const compact = this.isCompactLayout();
    if (sidebar === 'library') {
      if (compact && isOpen) {
        this.state.outlineOpen = false;
      }
      this.state.libraryOpen = isOpen;
    } else if (sidebar === 'outline') {
      if (compact && isOpen) {
        this.state.libraryOpen = false;
      }
      this.state.outlineOpen = isOpen;
    }
    this.applySidebarState();
    this.storageSet('docs_sidebar_state', {
      libraryOpen: this.state.libraryOpen,
      outlineOpen: this.state.outlineOpen,
    });
  }

  applySidebarState() {
    if (this.isCompactLayout() && this.state.libraryOpen && this.state.outlineOpen) {
      this.state.outlineOpen = false;
    }
    const layout = this.elements.docsLayout;
    layout.classList.toggle('left-collapsed', !this.state.libraryOpen);
    layout.classList.toggle('right-collapsed', !this.state.outlineOpen);
    this.elements.toggleLibraryBtn.classList.toggle('is-active', this.state.libraryOpen);
    this.elements.toggleOutlineBtn.classList.toggle('is-active', this.state.outlineOpen);
    this.applyBackdropState();
  }

  async decorateMarkdown(currentPath) {
    const headings = this.elements.renderedMarkdown.querySelectorAll('h1, h2, h3, h4, h5, h6');
    headings.forEach((heading) => {
      const id = this.slugify(heading.textContent || '');
      if (id) {
        heading.id = id;
      }
    });

    this.enhanceCodeBlocks();
    this.linkifyMarkdownReferences(currentPath);
    this.linkifyInlineCodeDocPaths(currentPath);

    const anchors = this.elements.renderedMarkdown.querySelectorAll('a[href]');
    anchors.forEach((anchor) => {
      // Plain-text / inline-code linkifiers already call applyDocumentNavigation.
      if (anchor.dataset.docPath) {
        return;
      }

      const href = anchor.getAttribute('href') || '';
      if (!href || href.startsWith('#') || href.startsWith('http://') || href.startsWith('https://')) {
        if (href.startsWith('http://') || href.startsWith('https://')) {
          anchor.target = '_blank';
          anchor.rel = 'noopener noreferrer';
        }
        return;
      }

      const resolved = this.resolveDocsPath(currentPath, href);
      if (!resolved || !resolved.isMarkdownDocument) {
        anchor.classList.add('link-disabled');
        anchor.title = 'Only markdown documents inside docs/ are navigable in this reader.';
        anchor.addEventListener('click', (event) => {
          event.preventDefault();
          this.toast('Only docs markdown links open in this reader.', 'error');
        });
        return;
      }

      this.applyDocumentNavigation(anchor, resolved);
    });

    const images = this.elements.renderedMarkdown.querySelectorAll('img[src]');
    images.forEach((image) => {
      const src = image.getAttribute('src') || '';
      if (!src || src.startsWith('http://') || src.startsWith('https://') || src.startsWith('data:')) {
        return;
      }
      const resolved = this.resolveDocsPath(currentPath, src, { allowAssets: true });
      if (resolved && resolved.isAsset) {
        image.src = `/docs-files/${resolved.path}`;
      }
    });

    await this.hydrateMermaidDiagrams();
  }

  enhanceCodeBlocks() {
    const codeBlocks = this.elements.renderedMarkdown.querySelectorAll('pre');
    codeBlocks.forEach((pre) => {
      if (pre.classList.contains('mermaid') || pre.closest('.mermaid-diagram-shell')) {
        return;
      }
      if (pre.parentElement && pre.parentElement.classList.contains('code-block-shell')) {
        return;
      }

      const code = pre.querySelector('code');
      const codeText = code ? (code.textContent || '') : (pre.textContent || '');
      if (!codeText.trim()) {
        return;
      }

      const wrapper = document.createElement('div');
      wrapper.className = 'code-block-shell';

      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'code-copy-btn';
      button.textContent = 'Copy';
      button.setAttribute('aria-label', 'Copy code block');
      button.addEventListener('click', async () => {
        const copied = await this.copyText(codeText);
        if (!copied) {
          button.textContent = 'Select';
          button.classList.add('is-error');
          this.selectCodeBlockContents(pre);
          this.toast('Copy is blocked here. The code is selected so you can copy it manually.', 'error');
          window.setTimeout(() => {
            button.textContent = 'Copy';
            button.classList.remove('is-error');
          }, 1800);
          return;
        }

        button.textContent = 'Copied';
        button.classList.add('is-success');
        this.toast('Code copied', 'success');
        window.setTimeout(() => {
          button.textContent = 'Copy';
          button.classList.remove('is-success');
        }, 1500);
      });

      pre.parentNode.insertBefore(wrapper, pre);
      wrapper.appendChild(button);
      wrapper.appendChild(pre);
    });
  }

  applyDocumentNavigation(anchor, resolved) {
    anchor.dataset.docPath = resolved.path;
    anchor.dataset.docHash = resolved.hash || '';
    anchor.href = `?path=${encodeURIComponent(resolved.path)}${resolved.hash ? `#${resolved.hash}` : ''}`;
    anchor.addEventListener('click', (event) => {
      event.preventDefault();
      this.selectDocument(resolved.path).then(() => {
        if (resolved.hash) {
          const target = document.getElementById(resolved.hash);
          if (target) {
            target.scrollIntoView({ behavior: 'smooth', block: 'start' });
          }
        }
      }).catch(() => {});
    });
  }

  linkifyMarkdownReferences(currentPath) {
    const pattern = /(^|[\s(>:-])((?:docs\/)?[A-Za-z0-9._/-]+\.md(?:#[A-Za-z0-9._-]+)?)/g;
    const textNodes = [];
    const walker = document.createTreeWalker(this.elements.renderedMarkdown, NodeFilter.SHOW_TEXT, {
      acceptNode: (node) => {
        if (!node.nodeValue || !node.nodeValue.trim()) {
          return NodeFilter.FILTER_REJECT;
        }
        const parent = node.parentElement;
        if (!parent || parent.closest('a, code, pre, h1, h2, h3, h4, h5, h6')) {
          return NodeFilter.FILTER_REJECT;
        }
        pattern.lastIndex = 0;
        return pattern.test(node.nodeValue) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
      }
    });

    let currentNode;
    while ((currentNode = walker.nextNode())) {
      textNodes.push(currentNode);
    }

    textNodes.forEach((textNode) => {
      const text = textNode.nodeValue || '';
      pattern.lastIndex = 0;
      const fragment = document.createDocumentFragment();
      let cursor = 0;
      let changed = false;
      let match;

      while ((match = pattern.exec(text)) !== null) {
        const prefix = match[1] || '';
        const reference = match[2] || '';
        const startIndex = match.index;
        const prefixIndex = startIndex + prefix.length;
        const resolved = this.resolveDocsPath(currentPath, reference);
        if (!resolved || !resolved.isMarkdownDocument) {
          continue;
        }

        const before = text.slice(cursor, startIndex);
        if (before) {
          fragment.appendChild(document.createTextNode(before));
        }
        if (prefix) {
          fragment.appendChild(document.createTextNode(prefix));
        }

        const anchor = document.createElement('a');
        anchor.textContent = reference;
        this.applyDocumentNavigation(anchor, resolved);
        fragment.appendChild(anchor);
        cursor = prefixIndex + reference.length;
        changed = true;
      }

      if (!changed) {
        return;
      }

      const after = text.slice(cursor);
      if (after) {
        fragment.appendChild(document.createTextNode(after));
      }
      textNode.parentNode.replaceChild(fragment, textNode);
    });
  }

  /**
   * Paths written as markdown inline code (`docs/Foo.md`) render as <code>; the plain-text
   * linkifier skips code nodes. Linkify when the entire span is only a resolvable .md path.
   */
  linkifyInlineCodeDocPaths(currentPath) {
    const linePattern = /^((?:docs\/)?[A-Za-z0-9._/-]+\.md)(#\S+)?$/;
    const codes = Array.from(this.elements.renderedMarkdown.querySelectorAll('code')).filter((el) => !el.closest('pre'));

    for (const code of codes) {
      if (code.closest('a')) {
        continue;
      }
      const raw = (code.textContent || '').trim();
      if (!linePattern.test(raw)) {
        continue;
      }
      const resolved = this.resolveDocsPath(currentPath, raw);
      if (!resolved || !resolved.isMarkdownDocument) {
        continue;
      }

      const link = document.createElement('a');
      link.className = 'inline-doc-ref';

      const inner = document.createElement('code');
      inner.textContent = raw;
      link.appendChild(inner);
      this.applyDocumentNavigation(link, resolved);
      code.parentNode.replaceChild(link, code);
    }
  }

  _safeDecodeURIComponent(value) {
    try {
      return decodeURIComponent(String(value));
    } catch (_e) {
      return String(value);
    }
  }

  _normalizePathSegments(segments) {
    const clean = [];
    for (const segment of segments) {
      if (!segment || segment === '.') {
        continue;
      }
      if (segment === '..') {
        if (!clean.length) {
          return null;
        }
        clean.pop();
        continue;
      }
      clean.push(segment);
    }
    return clean;
  }

  _relativePathFromBase(baseSegments, relativeHref) {
    const parts = relativeHref.split('/');
    const stack = baseSegments.slice();
    for (const p of parts) {
      if (p === '' || p === '.') {
        continue;
      }
      if (p === '..') {
        if (!stack.length) {
          return null;
        }
        stack.pop();
      } else {
        stack.push(p);
      }
    }
    return stack;
  }

  resolveDocsPath(currentPath, href, options = {}) {
    const allowAssets = Boolean(options.allowAssets);
    try {
      const [pathPartRaw, hashPart] = String(href).split('#');
      let normalizedPath = String(pathPartRaw || '').trim().split('?')[0];
      if (!normalizedPath) {
        return null;
      }

      try {
        normalizedPath = decodeURIComponent(normalizedPath);
      } catch (_e) {
        // Non-escaped href; continue with literal string.
      }

      if (normalizedPath.startsWith('/')) {
        const docsMarker = '/docs/';
        const docsIndex = normalizedPath.indexOf(docsMarker);
        if (docsIndex < 0) {
          return null;
        }
        normalizedPath = normalizedPath.slice(docsIndex + docsMarker.length);
      }

      const baseSegments = currentPath.split('/').filter(Boolean).slice(0, -1);
      const segments = normalizedPath.split('/').filter((s) => s !== '');

      if (!segments.length) {
        return null;
      }

      let resolvedParts;

      if (normalizedPath.startsWith('./') || normalizedPath.startsWith('../')) {
        resolvedParts = this._relativePathFromBase(baseSegments, normalizedPath);
        if (!resolvedParts) {
          return null;
        }
      } else if (segments[0] === 'docs') {
        resolvedParts = this._normalizePathSegments(segments.slice(1));
      } else if (segments.length === 1) {
        resolvedParts = this._normalizePathSegments(baseSegments.concat(segments));
      } else {
        resolvedParts = this._normalizePathSegments(segments);
      }

      if (!resolvedParts || resolvedParts.length === 0) {
        return null;
      }

      const resolvedPath = resolvedParts.join('/');
      const isMarkdownDocument = resolvedPath.toLowerCase().endsWith('.md');
      const isAsset = allowAssets && !isMarkdownDocument;
      if (!isMarkdownDocument && !isAsset) {
        return null;
      }
      return {
        path: resolvedPath,
        hash: hashPart ? this._safeDecodeURIComponent(hashPart) : '',
        isMarkdownDocument,
        isAsset,
      };
    } catch (_error) {
      return null;
    }
  }

  parseMarkdown(text) {
    if (typeof marked === 'undefined') {
      return this.escapeHtml(text).replace(/\n/g, '<br>');
    }

    if (!this._markedConfigured) {
      const renderer = new marked.Renderer();
      const defaultCode = renderer.code.bind(renderer);
      renderer.code = (codeOrToken, infostring, escaped) => {
        let rawCode = codeOrToken;
        let language = infostring || '';

        if (codeOrToken && typeof codeOrToken === 'object') {
          rawCode = codeOrToken.text || '';
          language = codeOrToken.lang || '';
        }

        const codeText = rawCode == null ? '' : String(rawCode);
        const languageLabel = String(language || '').trim().toLowerCase();
        if (languageLabel === 'mermaid') {
          const encodedSource = encodeURIComponent(codeText);
          return `
            <div class="mermaid-diagram-shell" data-mermaid-source="${encodedSource}">
              <div class="mermaid-loading">Rendering diagram…</div>
            </div>
          `;
        }

        return defaultCode(codeOrToken, infostring, escaped);
      };
      marked.use({ renderer, gfm: true, breaks: false });
      this._markedConfigured = true;
    }

    return marked.parse(text || '');
  }

  _ensureMermaidConfigured() {
    if (this._mermaidConfigured || typeof mermaid === 'undefined') {
      return;
    }

    mermaid.initialize({
      startOnLoad: false,
      theme: 'dark',
      securityLevel: 'strict',
    });
    this._mermaidConfigured = true;
  }

  async hydrateMermaidDiagrams() {
    const shells = this.elements.renderedMarkdown.querySelectorAll('.mermaid-diagram-shell[data-mermaid-source]');
    if (!shells.length) {
      return;
    }

    if (typeof mermaid === 'undefined') {
      shells.forEach((shell) => {
        const source = decodeURIComponent(shell.dataset.mermaidSource || '');
        shell.innerHTML = `<pre class="mermaid-fallback"><code>${this.escapeHtml(source)}</code></pre>`;
      });
      return;
    }

    this._ensureMermaidConfigured();

    const nodes = [];
    shells.forEach((shell) => {
      let source = '';
      try {
        source = decodeURIComponent(shell.dataset.mermaidSource || '');
      } catch (_error) {
        shell.innerHTML = '<div class="mermaid-error">Invalid diagram source.</div>';
        return;
      }

      const pre = document.createElement('pre');
      pre.className = 'mermaid';
      pre.textContent = source;
      shell.replaceChildren(pre);
      nodes.push(pre);
    });

    if (!nodes.length) {
      return;
    }

    try {
      await mermaid.run({ nodes });
    } catch (_error) {
      nodes.forEach((node) => {
        const shell = node.closest('.mermaid-diagram-shell');
        if (!shell) {
          return;
        }
        const source = node.textContent || '';
        shell.innerHTML = `
          <div class="mermaid-error">Diagram could not be rendered.</div>
          <pre class="mermaid-fallback"><code>${this.escapeHtml(source)}</code></pre>
        `;
      });
    }
  }

  async copyText(text) {
    const value = String(text || '');
    if (!value) {
      return false;
    }

    if (window.isSecureContext && navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
      try {
        await navigator.clipboard.writeText(value);
        return true;
      } catch (_error) {
        // Fall back below for browsers or contexts that reject Clipboard API writes.
      }
    }

    return this.legacyCopyText(value);
  }

  legacyCopyText(text) {
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.setAttribute('readonly', 'readonly');
    textarea.setAttribute('aria-hidden', 'true');
    textarea.style.position = 'fixed';
    textarea.style.top = '0';
    textarea.style.left = '-9999px';
    textarea.style.opacity = '0';
    document.body.appendChild(textarea);

    const selection = document.getSelection();
    const originalRange = selection && selection.rangeCount ? selection.getRangeAt(0) : null;

    textarea.focus();
    textarea.select();
    textarea.setSelectionRange(0, textarea.value.length);

    let copied = false;
    try {
      copied = document.execCommand('copy');
    } catch (_error) {
      copied = false;
    }

    document.body.removeChild(textarea);

    if (selection) {
      selection.removeAllRanges();
      if (originalRange) {
        selection.addRange(originalRange);
      }
    }

    return copied;
  }

  selectCodeBlockContents(pre) {
    const selection = window.getSelection();
    if (!selection) {
      return;
    }
    const range = document.createRange();
    range.selectNodeContents(pre);
    selection.removeAllRanges();
    selection.addRange(range);
  }

  folderLabel(folderPath) {
    return folderPath || 'All Docs';
  }

  formatDate(value) {
    if (!value) {
      return 'Unknown';
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

  syncUrl(path) {
    const url = new URL(window.location.href);
    url.searchParams.set('path', path);
    window.history.replaceState({}, '', url);
  }

  toast(message, type = 'success') {
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    this.elements.toastContainer.appendChild(toast);
    setTimeout(() => toast.remove(), 2200);
  }

  slugify(value) {
    return String(value || '')
      .trim()
      .toLowerCase()
      .replace(/[^\w\s-]/g, '')
      .replace(/\s+/g, '-')
      .replace(/-+/g, '-');
  }

  debounce(fn, wait) {
    let timeout;
    return (...args) => {
      window.clearTimeout(timeout);
      timeout = window.setTimeout(() => fn(...args), wait);
    };
  }

  escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text == null ? '' : String(text);
    return div.innerHTML;
  }

  storageGet(key, fallback = null) {
    try {
      const value = localStorage.getItem(key);
      return value ? JSON.parse(value) : fallback;
    } catch (_error) {
      return fallback;
    }
  }

  storageSet(key, value) {
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch (_error) {
      // Ignore localStorage failures.
    }
  }

  async authFetch(url, options = {}) {
    const headers = new Headers(options.headers || {});
    const token = localStorage.getItem('jarvis_auth_token');
    if (token) {
      headers.set('Authorization', `Bearer ${token}`);
    }
    const response = await fetch(url, { ...options, headers });
    if (response.status === 401) {
      localStorage.removeItem('jarvis_auth_token');
      document.cookie = 'jarvis_auth=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT';
      window.location.href = `/login?redirect=${encodeURIComponent(window.location.pathname + window.location.search)}`;
      throw new Error('Authentication required');
    }
    if (!response.ok) {
      let message = `HTTP ${response.status}`;
      try {
        const errorData = await response.clone().json();
        message = errorData.error || message;
      } catch (_error) {
        // Ignore JSON parse failure and fall back to status text.
      }
      throw new Error(message);
    }
    return response;
  }
}

window.addEventListener('DOMContentLoaded', () => {
  window.docsApp = new DocsApp();
});
