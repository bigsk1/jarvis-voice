/**
 * Jarvis Docs viewer — floating LLM assistant (POST /api/docs/assistant/chat)
 */
(function docsAssistantIIFE() {
  const STORAGE_MESSAGES = 'jarvisDocsAssistant.messages.v1';
  const STORAGE_UI = 'jarvisDocsAssistant.ui.v1';
  const STORAGE_MODE = 'jarvisDocsAssistant.mode.v1';

  class DocsAssistant {
    constructor() {
      this.messages = [];
      this._busy = false;
      /** True while awaiting assistant response (shows working row, disables input). */
      this._awaitingResponse = false;
      this.elements = {};

      try {
        const raw = localStorage.getItem(STORAGE_MESSAGES);
        if (raw) {
          const parsed = JSON.parse(raw);
          if (Array.isArray(parsed)) this.messages = parsed;
        }
      } catch (_) {
        /* ignore */
      }

      this._ensureDom();
      this._bind();
      this._restoreUiPrefs();
      this._restoreModePref();
      this._renderConversation();
    }

    _ensureDom() {
      let root = document.getElementById('docsAssistantRoot');
      if (!root) {
        root = document.createElement('div');
        root.id = 'docsAssistantRoot';
        root.className = 'docs-assistant';
        root.innerHTML = `
<button type="button" class="docs-assistant-fab" id="docsAssistantFab" title="Docs assistant" aria-label="Open Docs assistant">
  <span class="docs-assistant-fab-icon">📚</span>
</button>
<section class="docs-assistant-panel" id="docsAssistantPanel" aria-label="Documentation assistant chat" aria-hidden="true">
  <header class="docs-assistant-toolbar">
    <div class="docs-assistant-title">
      <span class="docs-assistant-brand">Docs assistant</span>
      <span class="docs-assistant-caption">Dedicated LLM · read-only excerpts from <code class="inline">docs/</code></span>
    </div>
    <div class="docs-assistant-toolbar-actions">
      <select id="docsAssistantModeSelect" class="docs-assistant-mode-select" title="Loads cloud.env vs local.env for LLM">
        <option value="cloud">Cloud LLM</option>
        <option value="local">Local LLM</option>
      </select>
      <button type="button" class="docs-assistant-icon-btn" id="docsAssistantSizeBtn" title="Toggle compact / expanded">⇕</button>
      <button type="button" class="docs-assistant-icon-btn" id="docsAssistantRefreshBtn" title="New conversation">＋</button>
      <button type="button" class="docs-assistant-icon-btn" id="docsAssistantCloseBtn" title="Close">✕</button>
    </div>
  </header>
  <div class="docs-assistant-meta" id="docsAssistantMeta" hidden></div>
  <div class="docs-assistant-messages" id="docsAssistantMessages" role="log"></div>
  <form class="docs-assistant-composer" id="docsAssistantForm">
    <textarea class="docs-assistant-input" id="docsAssistantInput" rows="1" maxlength="32000"
      placeholder="Ask about APIs, tools, workflows…"></textarea>
    <button type="submit" class="docs-assistant-send" id="docsAssistantSend">
      Ask
    </button>
  </form>
</section>`;
        document.body.appendChild(root);
      }

      this.root = root;
      this.elements.panel = root.querySelector('#docsAssistantPanel');
      this.elements.fab = root.querySelector('#docsAssistantFab');
      this.elements.messages = root.querySelector('#docsAssistantMessages');
      this.elements.input = root.querySelector('#docsAssistantInput');
      this.elements.form = root.querySelector('#docsAssistantForm');
      this.elements.meta = root.querySelector('#docsAssistantMeta');
      this.elements.modeSelect = root.querySelector('#docsAssistantModeSelect');
      this.elements.sizeBtn = root.querySelector('#docsAssistantSizeBtn');
      this.elements.closeBtn = root.querySelector('#docsAssistantCloseBtn');
      this.elements.refreshBtn = root.querySelector('#docsAssistantRefreshBtn');
    }

    _restoreModePref() {
      if (!this.elements.modeSelect) return;
      try {
        const m = localStorage.getItem(STORAGE_MODE);
        if (m === 'local' || m === 'cloud') {
          this.elements.modeSelect.value = m;
        }
      } catch (_) {
        /* ignore */
      }
    }

    _currentMode() {
      const v = this.elements.modeSelect?.value;
      return v === 'local' ? 'local' : 'cloud';
    }

    _toast(msg, type = 'success') {
      const tc = document.getElementById('toastContainer');
      if (!tc) return;
      const el = document.createElement('div');
      el.className = `toast ${type}`;
      el.textContent = msg;
      tc.appendChild(el);
      setTimeout(() => el.remove(), 2200);
    }

    _bind() {
      this.elements.fab.addEventListener('click', () => this.toggle());
      this.elements.closeBtn.addEventListener('click', () => this.hide());
      this.elements.refreshBtn.addEventListener('click', () => this.newChat());
      this.elements.sizeBtn.addEventListener('click', () => this.cycleSize());
      if (this.elements.modeSelect) {
        this.elements.modeSelect.addEventListener('change', () => {
          try {
            localStorage.setItem(STORAGE_MODE, this._currentMode());
          } catch (_) {
            /* ignore */
          }
        });
      }
      this.elements.form.addEventListener('submit', (e) => {
        e.preventDefault();
        this.send();
      });
      this.elements.input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault();
          this.send();
        }
      });
      document.addEventListener('keydown', (e) => {
        if (e.key !== 'Escape') return;
        if (this.root.classList.contains('docs-assistant--open')) {
          this.hide();
        }
      });
    }

    _restoreUiPrefs() {
      try {
        const u = JSON.parse(localStorage.getItem(STORAGE_UI) || '{}');
        if (u.expanded === true) this.root.classList.add('docs-assistant--expanded');
        else this.root.classList.remove('docs-assistant--expanded');
      } catch (_) {
        /* ignore */
      }
    }

    _saveMessages() {
      try {
        localStorage.setItem(STORAGE_MESSAGES, JSON.stringify(this.messages.slice(-80)));
      } catch (_) {
        /* quota */
      }
    }

    /**
     * Viewer ?path= is relative to docs/ only (sidebar uses `TOOL_CALLING_SYSTEM.md`).
     * Strip accidental `docs/` so the server does not look for docs/docs/…
     */
    docsViewerUrl(relPath, lineHint) {
      let path = String(relPath || '').trim().replace(/^\/+/, '').replace(/\\/g, '/');
      if (path.toLowerCase().startsWith('docs/')) {
        path = path.slice(5);
      }
      let hash = '';
      if (lineHint && Number(lineHint) > 0) {
        hash = `#line-${lineHint}`;
      }
      const origin = window.location.origin;
      return `${origin}/?path=${encodeURIComponent(path)}${hash}`;
    }

    _escapeHtml(text) {
      const div = document.createElement('div');
      div.textContent = text;
      return div.innerHTML;
    }

    _markdownToHtml(markdown) {
      if (!window.marked || typeof marked.parse !== 'function') {
        return this._escapeHtml(markdown || '');
      }
      return marked.parse(markdown || '', { breaks: true });
    }

    _linkifyDocBackticks(html) {
      let out = html;
      const reTick =
        /<code>((?:docs\/)?[A-Za-z0-9_./\-]+\.md)(?: \(\s*(?:line\s*)?(\d+)\s*\))?<\/code>/gi;
      out = out.replace(reTick, (match, docPath, line) => {
        const url = this.docsViewerUrl(docPath, line);
        const lbl = `${docPath}${line ? ` (line ${line})` : ''}`;
        return `<a class="inline-doc-assistant-ref" href="${url}">${lbl}</a>`;
      });
      return out;
    }

    _renderConversation() {
      const wrap = this.elements.messages;
      wrap.innerHTML = '';
      const frag = document.createDocumentFragment();

      if (!this.messages.length) {
        const intro = document.createElement('div');
        intro.className = 'docs-assistant-intro';
        intro.innerHTML = `
        <p>Ask questions about this repo. Answers use ripgrep text search over <code class="inline">docs/</code>; if <code class="inline">qmd</code> is installed, semantic search is included (see <code class="inline">docs/qmd/README.md</code>).</p>
        <p class="docs-assistant-hint">Citation links open in this reader; long answers may take 15–30s while retrieval + LLM run.</p>`;
        frag.appendChild(intro);
      }

      for (const m of this.messages) {
        const row = document.createElement('div');
        row.className = `docs-assistant-turn docs-assistant-turn--${m.role}`;
        const bubble = document.createElement('div');
        bubble.className = 'docs-assistant-bubble';
        if (m.role === 'user') {
          bubble.textContent = m.content;
        } else {
          let html = this._markdownToHtml(m.content);
          html = this._linkifyDocBackticks(html);
          bubble.innerHTML = html;
          if (Array.isArray(m.citations) && m.citations.length) {
            const foot = document.createElement('div');
            foot.className = 'docs-assistant-citations';
            foot.innerHTML = '<div class="docs-assistant-citations-title">Sources</div>';
            const ul = document.createElement('ul');
            m.citations.slice(0, 12).forEach((c) => {
              const li = document.createElement('li');
              const a = document.createElement('a');
              a.href = this.docsViewerUrl(c.path, c.line);
              a.textContent = `${c.title || c.path}${c.line ? ` — L${c.line}` : ''}`;
              li.appendChild(a);
              ul.appendChild(li);
            });
            foot.appendChild(ul);
            bubble.appendChild(foot);
          }
        }
        row.appendChild(bubble);
        frag.appendChild(row);
      }

      wrap.appendChild(frag);

      if (this._awaitingResponse) {
        const pending = document.createElement('div');
        pending.className = 'docs-assistant-thinking';
        pending.setAttribute('role', 'status');
        pending.setAttribute('aria-live', 'polite');
        pending.innerHTML =
          '<span class="docs-assistant-thinking-spinner" aria-hidden="true"></span>' +
          '<span class="docs-assistant-thinking-text">Working' +
          '<span class="docs-assistant-dots" aria-hidden="true"><span>.</span><span>.</span><span>.</span></span></span>';
        wrap.appendChild(pending);
      }

      wrap.scrollTop = wrap.scrollHeight;
    }

    toggle() {
      this.root.classList.toggle('docs-assistant--open');
      const open = this.root.classList.contains('docs-assistant--open');
      this.elements.panel.setAttribute('aria-hidden', open ? 'false' : 'true');
      if (open) {
        this.elements.input.focus();
      }
    }

    hide() {
      this.root.classList.remove('docs-assistant--open');
      this.elements.panel.setAttribute('aria-hidden', 'true');
    }

    cycleSize() {
      this.root.classList.toggle('docs-assistant--expanded');
      try {
        localStorage.setItem(
          STORAGE_UI,
          JSON.stringify({ expanded: this.root.classList.contains('docs-assistant--expanded') })
        );
      } catch (_) {
        /* ignore */
      }
    }

    newChat() {
      this.messages = [];
      this._awaitingResponse = false;
      this.elements.meta.hidden = true;
      this.elements.meta.textContent = '';
      this._saveMessages();
      this._renderConversation();
      this._toast('Assistant conversation cleared');
    }

    async send() {
      const raw = this.elements.input.value.trim();
      if (!raw || this._busy) return;

      const mode = this._currentMode();

      this.messages.push({ role: 'user', content: raw });
      this.elements.input.value = '';
      this._awaitingResponse = true;
      this.elements.input.disabled = true;
      this._saveMessages();
      this._renderConversation();

      this._busy = true;
      const sendBtn = this.elements.form.querySelector('button[type="submit"]');
      if (sendBtn) sendBtn.disabled = true;

      try {
        const resp = await fetch('/api/docs/assistant/chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ messages: this.messages, mode }),
        });
        const data = await resp.json().catch(() => ({}));

        if (!resp.ok || !data.ok) {
          throw new Error(data.error || resp.statusText || 'Request failed');
        }

        this.messages.push({
          role: 'assistant',
          content: data.message || '',
          citations: data.citations || [],
        });

        const metaParts = [];
        const R = data.retrieval;
        if (R && typeof R === 'object') {
          if (R.qmd_available === false) {
            metaParts.push(
              `${Number(R.grep_count) || 0} ripgrep · QMD not installed (optional)`
            );
          } else if (R.mode === 'none') {
            metaParts.push('no excerpts retrieved');
          } else if (R.mode === 'notes_only') {
            metaParts.push('retrieval notes only (no matching chunks)');
          } else {
            metaParts.push(
              `${Number(R.semantic_count) || 0} semantic · ${Number(R.grep_count) || 0} rg (${String(R.mode)})`
            );
          }
        }
        if (data.provider) metaParts.push(String(data.provider));
        if (data.model) metaParts.push(String(data.model));
        if (metaParts.length) {
          this.elements.meta.textContent = metaParts.join(' · ');
          this.elements.meta.hidden = false;
        }
      } catch (err) {
        console.error('[DocsAssistant]', err);
        this.messages.push({
          role: 'assistant',
          content:
            `Could not reach the docs assistant (${err.message || 'unknown error'}). ` +
            'Ensure the server can read the repo, `cloud.env` / `local.env` has LLM keys, and `rg` (ripgrep) is installed; QMD is optional.',
        });
      } finally {
        this._busy = false;
        this._awaitingResponse = false;
        this.elements.input.disabled = false;
        if (sendBtn) sendBtn.disabled = false;
        this._saveMessages();
        this._renderConversation();
      }
    }
  }

  const init = () => {
    try {
      window.docsAssistant = new DocsAssistant();
    } catch (e) {
      console.warn('[DocsAssistant] init skipped:', e);
    }
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
