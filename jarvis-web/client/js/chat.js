/**
 * Jarvis Web UI - Chat Interface
 */

class ChatUI {
  constructor() {
    this.messagesContainer = document.getElementById('chatMessages');
    this.inputField = document.getElementById('chatInput');
    this.sendBtn = document.getElementById('sendBtn');
    this.micBtn = document.getElementById('micBtn');
    this.enhanceBtn = document.getElementById('enhanceBtn');
    this.stopBtn = document.getElementById('stopBtn');
    
    // A bounded source bundle: analysis images and durable document artifacts.
    this.uploadBtn = document.getElementById('uploadBtn');
    this.fileInput = document.getElementById('fileInput');
    this.imagePreviewContainer = document.getElementById('imagePreviewContainer');
    this.imagePreviewStrip = document.getElementById('imagePreviewStrip');
    this.imageActionBadge = document.getElementById('imageActionBadge');
    this.clearAllImagesBtn = document.getElementById('clearAllImagesBtn');
    
    // Text/PDF/audio/video previews are rendered one row per selected source.
    this.filePreviewContainer = document.getElementById('filePreviewContainer');
    this.attachedDocuments = [];
    this._attachmentEpoch = 0;
    this._attachmentSend = null;
    this._imageUpload = null;
    this.pendingImageFiles = [];
    this._conversationLoadPending = false;
    
    // File conversion elements
    this.convertBtn = document.getElementById('convertBtn');
    this.convertInput = document.getElementById('convertInput');
    this.convertModal = document.getElementById('convertModal');
    this.convertTargetFormat = document.getElementById('convertTargetFormat');
    this.convertFileName = document.getElementById('convertFileName');
    this.convertPreview = document.getElementById('convertPreview');
    this.pendingConvertFile = null;  // {file, stashRef}
    this.convertPreviewUrl = null;
    
    // Image action modal elements
    this.imageActionModal = document.getElementById('imageActionModal');
    this.imageActionPreview = document.getElementById('imageActionPreview');
    this.pendingImageBatch = null;  // Upload results awaiting modal confirm
    
    this.currentMessageId = null;
    this.pendingTools = {};
    this.pendingToolsByMessage = new Map();
    this.pendingToolMessageId = null;
    this.activeToolCalls = new Set();
    this.processingPhaseDelayMs = 275;
    this._workingLabelTimer = null;
    this._workingLabelVisible = false;
    this.isProcessing = false;
    
    // Feedback toggle state
    this.feedbackEnabled = false;
    this.pendingFeedback = null;  // {message_id, status}
    
    // Voice recording state
    this.mediaRecorder = null;
    this.audioChunks = [];
    this.isRecording = false;
    this.recordingIndicator = null;
    this._voiceSession = null;
    
    // Image upload state
    this.attachedImages = [];  // [{ url, filename }]
    this.imageAttachmentAction = 'analyze';
    this.imageAttachmentSettings = {};
    this.pendingVisionRetryPayload = null;
    
    // Autocomplete state
    this.autocompleteEl = null;
    this.selectedSuggestionIndex = -1;
    this.autocompleteContext = null;
    this.toolHintsContainer = document.getElementById('toolHintsContainer');
    this.ambientToolSuggestionsEl = document.getElementById('ambientToolSuggestions');
    this.selectedToolHints = [];
    this.chatOnlyEnabled = false;
    
    // Token/cost tracking state
    this.tokenCounterEl = document.getElementById('tokenCounter');
    this.tokenCountEl = document.getElementById('tokenCount');
    this.tokenCostEl = document.getElementById('tokenCost');
    this.cumulativeTokens = { input: 0, output: 0, total: 0 };
    this.cumulativeModelCalls = 0;
    this.modelCallCountComplete = true;
    this.currentContextTokens = 0;
    this.currentContextEstimated = false;
    this.cumulativeCost = 0;
    this.cumulativeCache = {
      read: 0,
      creation: 0,
      writeCostUsd: 0,
      readCostUsd: 0,
      savingsUsd: 0,
    };
    // Ollama Cloud is subscription/compute-metered: cost is unknown, not $0.
    this.cumulativeUnknownCost = false;
    // Set when input tokens were approximated (provider omitted prompt_eval_count).
    this.cumulativeInputEstimated = false;
    this.contextWindow = 1000000;  // Conservative cloud fallback; updated from server/model catalog
    this.llmProvider = 'xai';      // Default, updated from server
    // When viewing a loaded conversation, lock stats to that thread's provider/model.
    this.tokenStatsLocked = false;
    this.tokenStatsMeta = {
      provider: null,
      model: null,
      mode: null,
      billingMode: null,
      contextWindow: null,
    };
    this.systemConfig = {};
    this.composerHintEl = document.getElementById('composerHint');
    this.composerHintTrack = document.getElementById('composerHintTrack');
    this.composerHintDots = document.getElementById('composerHintDots');
    this._composerHintIndex = 0;
    this._composerHintPaused = false;
    this._composerHintTimer = null;
    
    this._setupEventListeners();
    this._setupComposerHints();
    this._setupSocketListeners();
    this._setupVoiceRecording();
    this._setupImageUpload();
    this._setupImageActionModal();
    this._setupFileConversion();
    this._setupAutocomplete();
    this._setupEnhanceButton();
    this._renderToolHintChips();
    this._hideAmbientToolSuggestions();
    this.refreshContextWindow();  // Get actual context window for current model
  }

  _setupComposerHints() {
    this.inputField.placeholder = '';

    if (!this.composerHintEl || !this.composerHintTrack || !this.composerHintDots) {
      this.inputField.placeholder = 'Type / to use workflows';
      return;
    }

    // The overlay passes pointer events through to the textarea. Observe the
    // containing field so hovering still pauses rotation, including over keys.
    const hintHoverTarget = this.composerHintEl.parentElement;
    hintHoverTarget.addEventListener('mouseenter', () => {
      this._composerHintPaused = true;
    });
    hintHoverTarget.addEventListener('mouseleave', () => {
      this._composerHintPaused = false;
    });
    this.composerHintTrack.addEventListener('transitionend', (event) => {
      if (event.propertyName !== 'transform') return;
      const count = this._composerHints?.length || 0;
      if (!count || this._composerHintIndex < count) return;
      this._composerHintIndex = 0;
      this._applyComposerHintIndex({ jump: true });
    });
    document.addEventListener('jarvis:commands-updated', () => {
      this._renderComposerHintItems();
    });

    this._renderComposerHintItems();
    this._syncComposerHint();

    window.clearInterval(this._composerHintTimer);
    this._composerHintTimer = window.setInterval(() => {
      this._advanceComposerHint();
    }, 5200);
  }

  _composerHintDefinitions() {
    const hints = [
      { key: '/', label: 'for workflows', title: 'Insert / and browse workflows' },
      { key: '#', label: 'for tool hints', title: 'Insert # and browse tools' },
      { key: '@', label: 'for saved prompts', title: 'Insert @ and browse prompts' },
    ];
    // * is a bookmark_search workflow trigger. Hide it unless that workflow
    // is actually offered (tool enabled, not blocked, available in this mode).
    if (window.commandSystem?.getSuggestions?.('*')?.length) {
      hints.push({ key: '*', label: 'for bookmarks', title: 'Insert * and search bookmarks' });
    }
    return hints;
  }

  _renderComposerHintItems() {
    if (!this.composerHintTrack || !this.composerHintDots) return;

    const hints = this._composerHintDefinitions();
    const prevKey = this._composerHints?.[this._composerHintIndex % Math.max(this._composerHints.length, 1)]?.key;
    this._composerHints = hints;
    if (!hints.length) return;

    const items = [...hints, hints[0]];
    this.composerHintTrack.replaceChildren(...items.map((hint) => {
      const item = document.createElement('div');
      item.className = 'composer-hint-item';

      const key = document.createElement('button');
      key.type = 'button';
      key.className = 'composer-hint-key';
      key.dataset.prefix = hint.key;
      key.title = hint.title;
      key.tabIndex = -1;
      key.setAttribute('aria-label', hint.title);
      key.textContent = hint.key;
      key.addEventListener('click', (event) => {
        event.preventDefault();
        event.stopPropagation();
        this._insertComposerHint(hint.key);
      });

      const label = document.createElement('span');
      label.className = 'composer-hint-label';
      label.textContent = hint.label;

      item.append(key, label);
      return item;
    }));

    this.composerHintDots.replaceChildren(...hints.map(() => {
      const dot = document.createElement('span');
      dot.className = 'composer-hint-dot';
      return dot;
    }));

    const kept = hints.findIndex(hint => hint.key === prevKey);
    this._composerHintIndex = kept >= 0 ? kept : 0;
    this._applyComposerHintIndex({ jump: true });
  }

  _composerHintIsIdle() {
    return Boolean(this.inputField)
      && !this.inputField.value
      && !this.inputField.disabled
      && !this.inputField.readOnly
      && !this._voiceSession
      && !this.isProcessing
      && !this._conversationLoadPending;
  }

  _syncComposerHint() {
    if (!this.composerHintEl) return;
    const idle = this._composerHintIsIdle();
    this.composerHintEl.classList.toggle('is-hidden', !idle);
    this.composerHintEl.setAttribute('aria-hidden', String(!idle));
  }

  _applyComposerHintIndex({ jump = false } = {}) {
    if (!this.composerHintTrack || !this.composerHintDots) return;
    const count = this._composerHints?.length || 0;
    this.composerHintTrack.classList.toggle('is-jumping', jump);
    this.composerHintTrack.style.setProperty('--hint-index', String(this._composerHintIndex));
    if (jump) {
      void this.composerHintTrack.offsetHeight;
      this.composerHintTrack.classList.remove('is-jumping');
    }
    const active = count ? this._composerHintIndex % count : 0;
    this.composerHintDots.querySelectorAll('.composer-hint-dot').forEach((dot, index) => {
      dot.classList.toggle('is-active', index === active);
    });
  }

  _advanceComposerHint() {
    if (document.hidden || this._composerHintPaused || !this._composerHintIsIdle()) {
      this._syncComposerHint();
      return;
    }
    const count = this._composerHints?.length || 0;
    if (!count) return;
    this._composerHintIndex += 1;
    this._applyComposerHintIndex();
    this._syncComposerHint();
  }

  _insertComposerHint(prefix) {
    if (!this._composerHintIsIdle() || !prefix) return;
    this.inputField.value = prefix;
    this.inputField.focus();
    this.inputField.setSelectionRange(prefix.length, prefix.length);
    Utils.autoResize(this.inputField);
    this._checkAutocomplete();
    this._updateAmbientToolSuggestions();
    this._syncComposerHint();
  }
  
  /**
   * Fetch/refresh context window size for current model
   * Called on init and when settings change
   * @param {string} mode - Optional mode override ('cloud' or 'local')
   */
  async refreshContextWindow(mode = null) {
    try {
      // Use /api/settings which returns EFFECTIVE settings (with UI overrides)
      const requestedMode = mode || this.socket?.mode || 'cloud';
      const res = await fetch(`/api/settings?mode=${encodeURIComponent(requestedMode)}`);
      if (res.ok) {
        const data = await res.json();
        const settings = data.settings || {};
        
        // Get effective provider from settings (includes UI overrides)
        const provider = settings.llm?.provider?.value || 'xai';
        const modelId = settings.llm?.model?.value || '';
        const currentMode = settings.mode || mode || 'cloud';
        const providerModels =
          settings.provider_models?.[provider]
          || settings.llm?.model?.options
          || [];

        const parseContextString = (value) => {
          if (!value) return null;
          if (typeof value === 'number') return value;
          const raw = String(value).trim().toUpperCase();
          const match = raw.match(/^(\d+(?:\.\d+)?)([KM]?)$/);
          if (!match) return null;
          const amount = parseFloat(match[1]);
          const suffix = match[2];
          if (suffix === 'M') return Math.round(amount * 1_000_000);
          if (suffix === 'K') return Math.round(amount * 1_000);
          return Math.round(amount);
        };

        const selectedModel = providerModels.find((entry) => entry.id === modelId);
        const selectedContext = parseContextString(selectedModel?.context);
        
        // Set context window based on LLM provider (not TTS)
        if (selectedContext) {
          this.contextWindow = selectedContext;
        } else if (provider === 'xai') {
          // Catalog default is grok-4.3 with 1M context; selected models can override this.
          this.contextWindow = 1000000;
        } else if (provider === 'anthropic') {
          this.contextWindow = 1000000;
        } else if (provider === 'openai') {
          this.contextWindow = 128000;
        } else if (provider === 'ollama') {
          // Ask the active Ollama endpoint for the real context length. Cloud
          // execution may use a :cloud daemon card or an untagged canonical ID
          // from ollama.com; never substitute a local 32K num_ctx for either.
          const cloudTaggedModel = /(?:\:cloud|-cloud)$/i.test(String(modelId || ''));
          const cloudExecution = currentMode === 'cloud' || cloudTaggedModel;
          let resolved = null;
          if (modelId) {
            try {
              const ctxRes = await fetch(`/api/ollama/model-context?mode=${currentMode}&model=${encodeURIComponent(modelId)}`);
              if (ctxRes.ok) {
                const ctxData = await ctxRes.json();
                if (ctxData.context_length) resolved = parseInt(ctxData.context_length);
              }
            } catch {
              resolved = null;
            }
          }
          if (resolved) {
            this.contextWindow = resolved;
          } else if (cloudExecution) {
            this.contextWindow = null;
          } else {
            try {
              const sysRes = await fetch(`/api/settings/system?mode=${currentMode}`);
              if (sysRes.ok) {
                const sysData = await sysRes.json();
                const sysConfig = sysData.config || {};
                this.contextWindow = parseInt(sysConfig.OLLAMA_CONTEXT_WINDOW) || 32768;
              } else {
                this.contextWindow = 32768;
              }
            } catch {
              this.contextWindow = 32768;
            }
          }
        }

        await this._refreshSystemConfig(currentMode);
        
        this.llmProvider = provider;  // Store for display
        if (!this.tokenStatsLocked) {
          this.tokenStatsMeta = {
            provider,
            model: modelId || null,
            mode: currentMode,
            billingMode: null,
            contextWindow: Number.isFinite(this.contextWindow) ? this.contextWindow : null,
          };
        }
        const contextLabel = Number.isFinite(this.contextWindow)
          ? `${this.contextWindow.toLocaleString()} tokens`
          : 'managed/unknown';
        console.log('[Chat] LLM Provider:', provider, '| Context window:', contextLabel);
      }
    } catch (err) {
      console.warn('[Chat] Could not fetch context window:', err);
    }
  }

  async _refreshSystemConfig(mode = null) {
    try {
      const currentMode = mode || this.socket?.mode || 'cloud';
      const res = await fetch(`/api/settings/system?mode=${encodeURIComponent(currentMode)}`);
      if (!res.ok) return;
      const data = await res.json();
      this.systemConfig = data.config || {};
    } catch (err) {
      console.warn('[Chat] Could not fetch system config:', err);
    }
  }

  _getOpenCodeSessionUrl(sessionId) {
    if (!sessionId) return null;

    const configuredBase = this.systemConfig?.OPENCODE_BASE_URL || 'http://localhost:4096';

    try {
      const base = new URL(configuredBase);
      const pageProtocol = window.location.protocol || base.protocol;
      const pageHost = window.location.hostname || base.hostname;
      const needsBrowserHost = ['localhost', '127.0.0.1', '0.0.0.0'].includes(base.hostname);
      const finalHost = needsBrowserHost ? pageHost : base.hostname;
      const port = base.port || '4096';
      return `${pageProtocol}//${finalHost}:${port}/Lw/session/${encodeURIComponent(sessionId)}`;
    } catch {
      const pageProtocol = window.location.protocol || 'http:';
      const pageHost = window.location.hostname || 'localhost';
      return `${pageProtocol}//${pageHost}:4096/Lw/session/${encodeURIComponent(sessionId)}`;
    }
  }

  /**
   * Setup DOM event listeners
   */
  _setupEventListeners() {
    // Keep a Cancel press a cancellation if STT finishes before its click fires.
    this.sendBtn.addEventListener('pointerdown', () => {
      this._sendClickCancelsDictation = Boolean(this._voiceSession);
    });
    this.sendBtn.addEventListener('keydown', (e) => {
      if ((e.key === 'Enter' || e.key === ' ') && !e.repeat) {
        this._sendClickCancelsDictation = Boolean(this._voiceSession);
      }
    });
    this.sendBtn.addEventListener('click', () => {
      const cancel = this._sendClickCancelsDictation || this._voiceSession;
      this._sendClickCancelsDictation = false;
      if (cancel) this._cancelRecording();
      else this.sendMessage();
    });
    
    // Stop button - cancel processing
    this.stopBtn.addEventListener('click', () => this.cancelProcessing());
    
    // Enter to send (Shift+Enter for new line), arrow keys for autocomplete
    this.inputField.addEventListener('keydown', (e) => {
      // Handle autocomplete navigation
      if (this.autocompleteEl && this.autocompleteEl.style.display !== 'none') {
        if (e.key === 'ArrowDown') {
          e.preventDefault();
          this._navigateSuggestion(1);
          return;
        } else if (e.key === 'ArrowUp') {
          e.preventDefault();
          this._navigateSuggestion(-1);
          return;
        } else if (e.key === 'Tab' || e.key === 'Enter') {
          if (this.selectedSuggestionIndex >= 0) {
            e.preventDefault();
            this._selectSuggestion(this.selectedSuggestionIndex);
            return;
          }
        } else if (e.key === 'Escape') {
          this._hideAutocomplete();
          return;
        }
      }
      
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        this.sendMessage();
      }
    });
    
    // Auto-resize input and check for autocomplete
    this.inputField.addEventListener('input', () => {
      Utils.autoResize(this.inputField);
      this._checkAutocomplete();
      this._updateAmbientToolSuggestions();
      this._syncComposerHint();
    });
  }
  
  /**
   * Setup autocomplete dropdown
   */
  _setupAutocomplete() {
    // Create autocomplete container
    this.autocompleteEl = document.createElement('div');
    this.autocompleteEl.className = 'autocomplete-dropdown';
    this.autocompleteEl.style.display = 'none';
    
    // Insert after input container
    const inputContainer = document.querySelector('.chat-input-container');
    if (inputContainer) {
      inputContainer.style.position = 'relative';
      inputContainer.appendChild(this.autocompleteEl);
    }
    
    // Click outside to close
    document.addEventListener('click', (e) => {
      if (!this.autocompleteEl.contains(e.target) && e.target !== this.inputField) {
        this._hideAutocomplete();
      }
    });
  }
  
  /**
   * Setup the ✨ Enhance with AI button
   */
  _setupEnhanceButton() {
    if (!this.enhanceBtn) {
      console.warn('[Chat] Enhance button not found');
      return;
    }
    
    this.enhanceBtn.addEventListener('click', async () => {
      await this._enhancePrompt();
    });
    
    console.log('[Chat] ✨ Enhance button ready');
  }

  _combineToolHints(inlineHints = []) {
    const combined = [];
    for (const name of [...this.selectedToolHints, ...(inlineHints || [])]) {
      if (combined.length >= window.commandSystem.maxToolHints) break;
      if (combined.includes(name)) continue;
      if (!window.commandSystem.getTool(name)) continue;
      combined.push(name);
    }
    return combined;
  }

  _escapeAttr(value) {
    return Utils.escapeHtml(value).replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  _addToolHint(name, options = {}) {
    if (!name || !window.commandSystem.getTool(name)) return false;
    if (this.chatOnlyEnabled) {
      Utils.toast('Turn off Chat only before selecting tools', 'info');
      return false;
    }
    if (this.selectedToolHints.includes(name)) {
      if (options.focus !== false) this.inputField.focus();
      return true;
    }
    if (this.selectedToolHints.length >= window.commandSystem.maxToolHints) {
      Utils.toast(`Tool hints are capped at ${window.commandSystem.maxToolHints}`, 'info');
      return false;
    }

    this.selectedToolHints.push(name);
    this._renderToolHintChips();
    this._updateAmbientToolSuggestions();
    if (options.focus !== false) this.inputField.focus();
    return true;
  }

  _removeToolHint(name) {
    this.selectedToolHints = this.selectedToolHints.filter(item => item !== name);
    this._renderToolHintChips();
    this._updateAmbientToolSuggestions();
    this.inputField.focus();
  }

  _setChatOnlyEnabled(enabled, options = {}) {
    const next = Boolean(enabled);
    if (next && this.selectedToolHints.length > 0) {
      this.selectedToolHints = [];
    }
    if (next) {
      this.feedbackEnabled = false;
    }
    this.chatOnlyEnabled = next;
    this._syncFeedbackControl();
    this._renderToolHintChips();
    this._updateAmbientToolSuggestions();
    if (options.focus !== false) this.inputField.focus();
  }

  _renderToolHintChips() {
    if (!this.toolHintsContainer) return;

    if (this.selectedToolHints.length === 0 && !this.chatOnlyEnabled) {
      this.toolHintsContainer.innerHTML = '';
      this.toolHintsContainer.style.display = 'none';
      return;
    }

    const policyChip = this.chatOnlyEnabled ? `
      <span class="tool-hint-chip chat-only-chip" title="Chat only: Tool RAG and provider-hosted tools are disabled">
        <span class="tool-hint-name">Chat only</span>
        <button type="button" class="tool-hint-remove chat-only-remove" title="Turn off Chat only">x</button>
      </span>
    ` : '';
    const chips = this.selectedToolHints.map(name => `
      <span class="tool-hint-chip" title="Prefer ${this._escapeAttr(name)} for this request">
        <span class="tool-hint-name">#${Utils.escapeHtml(name)}</span>
        <button type="button" class="tool-hint-remove" data-tool="${this._escapeAttr(name)}" title="Remove #${this._escapeAttr(name)}">x</button>
      </span>
    `).join('');

    this.toolHintsContainer.innerHTML = `
      <span class="tool-hint-label">${this.chatOnlyEnabled ? 'Mode' : 'Tool hints'}</span>
      ${policyChip}
      ${chips}
    `;
    this.toolHintsContainer.style.display = 'flex';

    this.toolHintsContainer.querySelectorAll('.tool-hint-remove').forEach(button => {
      if (button.classList.contains('chat-only-remove')) {
        button.addEventListener('click', () => this._setChatOnlyEnabled(false));
        return;
      }
      button.addEventListener('click', () => this._removeToolHint(button.dataset.tool));
    });
  }

  _hideAmbientToolSuggestions() {
    if (!this.ambientToolSuggestionsEl) return;
    this.ambientToolSuggestionsEl.innerHTML = '';
    this.ambientToolSuggestionsEl.style.display = 'none';
  }

  _updateAmbientToolSuggestions() {
    if (!this.ambientToolSuggestionsEl) return;
    if (this.chatOnlyEnabled) {
      this._hideAmbientToolSuggestions();
      return;
    }
    if (this.isProcessing) {
      this._hideAmbientToolSuggestions();
      return;
    }
    if (this.autocompleteEl && this.autocompleteEl.style.display !== 'none') {
      this._hideAmbientToolSuggestions();
      return;
    }

    const input = this.inputField.value || '';
    const trimmed = input.trim();
    if (trimmed.length < 8 || /^[\/@*]/.test(trimmed)) {
      this._hideAmbientToolSuggestions();
      return;
    }

    const cursor = this.inputField.selectionStart ?? input.length;
    const activeToolToken = input.slice(0, cursor).match(/(^|\s)#([A-Za-z0-9_-]*)$/);
    if (activeToolToken) {
      this._hideAmbientToolSuggestions();
      return;
    }

    const parsed = window.commandSystem.parseInput(input);
    const selectedNames = this._combineToolHints(parsed.toolHints || []);
    const suggestionText = parsed.message || trimmed;
    const suggestions = window.commandSystem.getAmbientToolSuggestions(suggestionText, selectedNames, 3);
    if (suggestions.length === 0) {
      this._hideAmbientToolSuggestions();
      return;
    }

    this.ambientToolSuggestionsEl.innerHTML = `
      <span class="ambient-suggestion-label">Suggested tools</span>
      ${suggestions.map(tool => `
        <button type="button" class="ambient-tool-chip" data-tool="${this._escapeAttr(tool.name)}" title="Add #${this._escapeAttr(tool.name)}">
          #${Utils.escapeHtml(tool.name)}
        </button>
      `).join('')}
    `;
    this.ambientToolSuggestionsEl.style.display = 'flex';

    this.ambientToolSuggestionsEl.querySelectorAll('.ambient-tool-chip').forEach(button => {
      button.addEventListener('click', () => {
        this._addToolHint(button.dataset.tool);
      });
    });
  }
  
  /**
   * ✨ Enhance the current input with AI
   * Transforms rough user input into an optimal prompt using full Jarvis knowledge
   */
  async _enhancePrompt() {
    if (this._voiceSession) return;
    const input = this.inputField.value.trim();

    if (this.chatOnlyEnabled) {
      Utils.toast('Turn off Chat only before enhancing with AI tools', 'info');
      return;
    }
    
    if (!input) {
      Utils.toast('Type something first, then click ✨ to enhance', 'info');
      return;
    }
    
    // Don't enhance if already using workflows/prompts
    if (input.startsWith('/') || input.startsWith('@') || input.startsWith('*')) {
      Utils.toast('Remove the /, @, or * prefix first to enhance', 'info');
      return;
    }

    const parsedInput = window.commandSystem.parseInput(input);
    const toolHints = this._combineToolHints(parsedInput.toolHints || []);
    const inputToEnhance = parsedInput.message || input;

    if (!inputToEnhance) {
      Utils.toast('Add a task after the tool hint before enhancing', 'info');
      return;
    }
    
    // Show loading state
    this.enhanceBtn.classList.add('enhancing');
    this.enhanceBtn.disabled = true;
    const originalTitle = this.enhanceBtn.title;
    this.enhanceBtn.title = 'Enhancing...';
    
    try {
      const imagePayload = this._getImageAttachmentPayload();
      const activeMode = window.jarvisSocket?.mode || 'cloud';
      const response = await fetch('/api/enhance-prompt', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          input: inputToEnhance,
          mode: activeMode,
          tool_hints: toolHints,
          image_action: imagePayload?.action || null,
          image: imagePayload?.images?.[0] || null
        })
      });
      
      const data = await response.json();
      
      if (data.ok && data.enhanced) {
        this.selectedToolHints = toolHints;
        this._renderToolHintChips();

        // Replace input with enhanced clean task text. Tool hints stay as chips.
        this.inputField.value = data.enhanced;
        Utils.autoResize(this.inputField);
        this._updateAmbientToolSuggestions();
        
        // Show success feedback
        if (data.vision_warning) {
          Utils.toast(`⚠️ ${data.vision_warning}`, 'warning', 5000);
        } else {
          Utils.toast(data.vision_grounded ? '✨ Prompt enhanced with image context!' : '✨ Prompt enhanced!', 'success', 2000);
        }
        
        // Focus and move cursor to end
        this.inputField.focus();
        this.inputField.setSelectionRange(
          this.inputField.value.length,
          this.inputField.value.length
        );
      } else {
        Utils.toast(data.error || 'Failed to enhance prompt', 'error');
      }
    } catch (err) {
      console.error('[Chat] Enhance error:', err);
      Utils.toast('Failed to enhance prompt', 'error');
    } finally {
      // Reset button state
      this.enhanceBtn.classList.remove('enhancing');
      this.enhanceBtn.disabled = false;
      this.enhanceBtn.title = originalTitle;
    }
  }
  
  /**
   * Check input for autocomplete triggers
   */
  _checkAutocomplete() {
    const input = this.inputField.value;
    const cursor = this.inputField.selectionStart ?? input.length;
    this.autocompleteContext = null;

    // Tool hints can appear anywhere as standalone #tool tokens.
    const toolToken = input.slice(0, cursor).match(/(^|\s)#([A-Za-z0-9_-]*)$/);
    if (toolToken) {
      const query = toolToken[2] || '';
      const start = cursor - query.length - 1;
      const suggestions = window.commandSystem.getSuggestions(`#${query}`);
      if (suggestions.length > 0) {
        this.autocompleteContext = { type: 'tool', start, end: cursor };
        this._showAutocomplete(suggestions);
        return;
      }
    }
    
    // Case 1: Start with / and no space yet (typing workflow)
    if (input.startsWith('/') && !input.includes(' ')) {
      const suggestions = window.commandSystem.getSuggestions(input);
      if (suggestions.length > 0) {
        this.autocompleteContext = { type: 'workflow', start: 0, end: input.length };
        this._showAutocomplete(suggestions);
        return;
      }
    }
    
    // Case 2: Start with @ and no space yet (typing prompt only)
    if (input.startsWith('@') && !input.includes(' ')) {
      const suggestions = window.commandSystem.getSuggestions(input);
      if (suggestions.length > 0) {
        this.autocompleteContext = { type: 'prompt', start: 0, end: input.length };
        this._showAutocomplete(suggestions);
        return;
      }
    }
    
    // Case 3: Start with * and no space yet (bookmark search - Firefox-style)
    if (input.startsWith('*') && !input.includes(' ')) {
      const suggestions = window.commandSystem.getSuggestions(input);
      if (suggestions.length > 0) {
        this.autocompleteContext = { type: 'workflow', start: 0, end: input.length };
        this._showAutocomplete(suggestions);
        return;
      }
    }
    
    this._hideAutocomplete();
  }
  
  /**
   * Show autocomplete dropdown
   * @param {Array} suggestions - List of suggestions
   */
  _showAutocomplete(suggestions) {
    this.selectedSuggestionIndex = -1;
    this._hideAmbientToolSuggestions();
    
    const html = suggestions.map((s, i) => {
      // Build tooltip content for workflows
      let tooltipHtml = '';
      if (s.type === 'workflow' && s.steps && s.steps.length > 0) {
        const stepsHtml = s.steps.map(step => 
          `<div class="tooltip-step">
            <span class="tooltip-step-num">${step.step}.</span>
            <span class="tooltip-step-tool">${step.tool}${step.action ? '.' + step.action : ''}</span>
            ${step.description ? `<span class="tooltip-step-desc">- ${step.description}</span>` : ''}
          </div>`
        ).join('');
        tooltipHtml = `
          <div class="workflow-tooltip">
            <div class="tooltip-header">${s.name}</div>
            <div class="tooltip-steps">${stepsHtml}</div>
          </div>
        `;
      }
      // Build tooltip content for prompts
      else if (s.type === 'prompt' && s.key_points && s.key_points.length > 0) {
        const pointsHtml = s.key_points.map((point, idx) => 
          `<div class="tooltip-step">
            <span class="tooltip-step-num">•</span>
            <span class="tooltip-step-desc">${point}</span>
          </div>`
        ).join('');
        tooltipHtml = `
          <div class="workflow-tooltip prompt-tooltip">
            <div class="tooltip-header">${s.description || s.name}</div>
            <div class="tooltip-steps">${pointsHtml}</div>
          </div>
        `;
      }
      else if (s.type === 'tool') {
        tooltipHtml = `
          <div class="workflow-tooltip tool-tooltip">
            <div class="tooltip-header">${s.name}</div>
            <div class="tooltip-steps">
              <div class="tooltip-step">
                <span class="tooltip-step-num">${s.source === 'mcp' ? 'MCP' : 'Tool'}</span>
                <span class="tooltip-step-desc">${Utils.escapeHtml(s.description || '')}</span>
              </div>
            </div>
          </div>
        `;
      }
      else if (s.type === 'policy') {
        tooltipHtml = `
          <div class="workflow-tooltip tool-tooltip">
            <div class="tooltip-header">Chat only</div>
            <div class="tooltip-steps">
              <div class="tooltip-step">
                <span class="tooltip-step-num">Mode</span>
                <span class="tooltip-step-desc">${Utils.escapeHtml(s.description || '')}</span>
              </div>
            </div>
          </div>
        `;
      }
      
      const displayPrefix = s.prefix || (s.type === 'prompt' ? '@' : '/');
      return `
        <div class="autocomplete-item" data-index="${i}" data-type="${s.type}" data-name="${s.name}" data-prefix="${displayPrefix}">
          <span class="autocomplete-icon">${s.icon}</span>
          <span class="autocomplete-name">${displayPrefix}${s.name}</span>
          <span class="autocomplete-desc">${Utils.escapeHtml(s.description || '')}</span>
          ${tooltipHtml}
        </div>
      `;
    }).join('');
    
    this.autocompleteEl.innerHTML = html;
    this.autocompleteEl.style.display = 'block';
    
    // Add click handlers
    this.autocompleteEl.querySelectorAll('.autocomplete-item').forEach(item => {
      item.addEventListener('click', () => {
        const index = parseInt(item.dataset.index);
        this._selectSuggestion(index);
      });
      item.addEventListener('mouseenter', (e) => {
        this._highlightSuggestion(parseInt(item.dataset.index));
        // Position tooltip BELOW the row so it doesn't cover the command
        const tooltip = item.querySelector('.workflow-tooltip, .prompt-tooltip, .tool-tooltip');
        if (tooltip) {
          const rect = item.getBoundingClientRect();
          tooltip.style.display = 'block';
          tooltip.style.top = `${rect.bottom + 6}px`;
          tooltip.style.left = `${rect.left}px`;
          // Keep tooltip on screen
          const tooltipRect = tooltip.getBoundingClientRect();
          if (tooltipRect.right > window.innerWidth) {
            tooltip.style.left = `${rect.right - tooltipRect.width}px`;
          }
          if (tooltipRect.bottom > window.innerHeight) {
            tooltip.style.top = `${rect.top - tooltipRect.height - 6}px`;
          }
          if (parseFloat(tooltip.style.left) < 8) {
            tooltip.style.left = '8px';
          }
        }
      });
      item.addEventListener('mouseleave', () => {
        const tooltip = item.querySelector('.workflow-tooltip, .prompt-tooltip, .tool-tooltip');
        if (tooltip) {
          tooltip.style.display = 'none';
        }
      });
    });
  }
  
  /**
   * Hide autocomplete dropdown
   */
  _hideAutocomplete() {
    if (this.autocompleteEl) {
      this.autocompleteEl.style.display = 'none';
      this.selectedSuggestionIndex = -1;
      this.autocompleteContext = null;
    }
  }
  
  /**
   * Navigate suggestions with arrow keys
   */
  _navigateSuggestion(direction) {
    const items = this.autocompleteEl.querySelectorAll('.autocomplete-item');
    if (items.length === 0) return;
    
    this.selectedSuggestionIndex += direction;
    if (this.selectedSuggestionIndex < 0) this.selectedSuggestionIndex = items.length - 1;
    if (this.selectedSuggestionIndex >= items.length) this.selectedSuggestionIndex = 0;
    
    this._highlightSuggestion(this.selectedSuggestionIndex);
  }
  
  /**
   * Highlight a suggestion
   */
  _highlightSuggestion(index) {
    const items = this.autocompleteEl.querySelectorAll('.autocomplete-item');
    items.forEach((item, i) => {
      item.classList.toggle('selected', i === index);
    });
    this.selectedSuggestionIndex = index;
    // Keep selected item in view when using arrow keys
    const selected = items[index];
    if (selected) {
      selected.scrollIntoView({ block: 'nearest', behavior: 'auto' });
    }
  }
  
  /**
   * Select a suggestion
   */
  _selectSuggestion(index) {
    const items = this.autocompleteEl.querySelectorAll('.autocomplete-item');
    const item = items[index];
    if (!item) return;
    
    const type = item.dataset.type;
    const name = item.dataset.name;
    const prefix = item.dataset.prefix || (type === 'prompt' ? '@' : '/');

    if (type === 'policy' && this.autocompleteContext) {
      const currentVal = this.inputField.value;
      const { start, end } = this.autocompleteContext;
      const before = currentVal.slice(0, start);
      const after = currentVal.slice(end);
      this.inputField.value = `${before}${after.replace(/^\s+/, '')}`.replace(/[ \t]{2,}/g, ' ');
      const cursor = Math.min(before.length, this.inputField.value.length);
      this._setChatOnlyEnabled(true, { focus: false });
      this.inputField.focus();
      this.inputField.setSelectionRange(cursor, cursor);
      Utils.autoResize(this.inputField);
      this._hideAutocomplete();
      this._syncComposerHint();
      return;
    }

    if (type === 'tool' && this.autocompleteContext) {
      const currentVal = this.inputField.value;
      const { start, end } = this.autocompleteContext;
      const before = currentVal.slice(0, start);
      const after = currentVal.slice(end);
      this.inputField.value = `${before}${after.replace(/^\s+/, '')}`.replace(/[ \t]{2,}/g, ' ');
      const cursor = Math.min(before.length, this.inputField.value.length);
      this._addToolHint(name, { focus: false });
      this.inputField.focus();
      this.inputField.setSelectionRange(cursor, cursor);
      Utils.autoResize(this.inputField);
      this._hideAutocomplete();
      this._updateAmbientToolSuggestions();
      this._syncComposerHint();
      return;
    }
    
    // Replace entire input with selected workflow/prompt + space
    // For * bookmarks: preserve query after * if user already typed it (e.g. *docker -> *docker )
    const currentVal = this.inputField.value;
    const afterStar = prefix === '*' && currentVal.startsWith('*') ? currentVal.slice(1).trim() : '';
    this.inputField.value = prefix === '*' ? `*${afterStar ? ' ' + afterStar : ''} ` : `${prefix}${name} `;
    
    this.inputField.focus();
    this._hideAutocomplete();
    this._syncComposerHint();
  }

  /**
   * Setup voice recording (click-to-toggle mode)
   * Click once to record, click again to transcribe into the editable draft.
   */
  _setupVoiceRecording() {
    if (!this.micBtn) return;
    
    // Check for basic mediaDevices support (actual permission checked on first use)
    const hasMediaDevices = !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
    
    if (!hasMediaDevices) {
      console.warn('[Chat] MediaDevices API not available - likely private browsing or unsecured context');
      this.micBtn.title = 'Voice input requires HTTPS or localhost (try a regular browser window)';
      this.micBtn.style.opacity = '0.5';
      this.micBtn.style.cursor = 'not-allowed';
      
      // Still add click handler to show helpful message
      this.micBtn.addEventListener('click', () => {
        Utils.toast('🎤 Voice input requires a secure context (HTTPS) or try a non-private browser window', 'warning', 5000);
      });
      return;
    }
    
    // Click-to-toggle: click starts, click again stops
    this.micBtn.addEventListener('click', (e) => {
      e.preventDefault();
      if (this.isRecording) {
        this._stopRecording();
      } else {
        this._startRecording();
      }
    });
    
    // Native button activation handles Space and Enter once per key press.
    // Escape to cancel
    document.addEventListener('keydown', (e) => {
      if (e.code === 'Escape' && this._voiceSession) {
        this._cancelRecording();
      }
    });
    window.addEventListener('pagehide', () => this._cancelRecording({ silent: true }));
  }

  _voiceContextIsCurrent(session) {
    return this._voiceSession === session && !session.controller.signal.aborted
      && !this._conversationLoadPending
      && session.mode === (window.jarvisSocket?.mode || 'cloud')
      && session.conversationId === (window.jarvisSocket?.conversationId || null);
  }
  
  /**
   * Start voice recording with ready indicator
   */
  async _startRecording() {
    if (this._talkActive || this._voiceSession || this.isProcessing || this._conversationLoadPending
        || this.enhanceBtn?.classList.contains('enhancing')) return;

    // Own permission requests, recorder events and transcription as one operation.
    const session = {
      phase: 'preparing',
      mode: window.jarvisSocket?.mode || 'cloud',
      conversationId: window.jarvisSocket?.conversationId || null,
      controller: new AbortController(),
      stream: null,
      recorder: null,
      chunks: []
    };
    this._voiceSession = session;
    this.micBtn.classList.add('preparing');
    this.micBtn.title = 'Preparing...';
    this.micBtn.setAttribute('aria-label', this.micBtn.title);
    this.micBtn.disabled = true;
    this.updateSendButton();

    try {
      // Request microphone access
      const stream = await navigator.mediaDevices.getUserMedia({ 
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          sampleRate: 16000
        }
      });
      
      if (!this._voiceContextIsCurrent(session)) {
        stream.getTracks().forEach(track => track.stop());
        this._resetMicButton(session);
        return;
      }
      session.stream = stream;
      const mimeType = this._getSupportedMimeType();
      const recorder = session.recorder = new MediaRecorder(stream, { mimeType });
      this.mediaRecorder = recorder;
      this.audioChunks = session.chunks;
      this._recordingStream = stream;

      recorder.ondataavailable = (e) => {
        if (this._voiceContextIsCurrent(session) && e.data.size > 0) {
          session.chunks.push(e.data);
        }
      };

      recorder.onstop = () => {
        stream.getTracks().forEach(track => track.stop());
        if (this._voiceContextIsCurrent(session)) {
          this._processRecording(session);
        } else {
          this._resetMicButton(session);
        }
      };
      recorder.onerror = () => {
        if (this._voiceContextIsCurrent(session)) {
          Utils.toast('Recording failed. Your draft is unchanged.', 'error');
        }
        this._resetMicButton(session);
      };

      recorder.start(100);
      session.phase = 'recording';
      this.isRecording = true;
      this.micBtn.disabled = false;
      this.micBtn.classList.remove('preparing');
      this.micBtn.classList.add('recording');
      this.micBtn.title = 'Stop recording and add text to draft';
      this.micBtn.setAttribute('aria-label', this.micBtn.title);
      this.micBtn.setAttribute('aria-pressed', 'true');
      this._showRecordingIndicator();
      Utils.toast('🎤 Listening. Click mic to finish; × to cancel.', 'info', 3000);
    } catch (err) {
      if (!this._voiceContextIsCurrent(session)) {
        this._resetMicButton(session);
        return;
      }
      if (err.name === 'NotAllowedError') {
        Utils.toast('Microphone access denied. Click the lock icon in your browser address bar to allow.', 'error', 5000);
      } else if (err.name === 'NotFoundError') {
        Utils.toast('No microphone found', 'error');
      } else {
        Utils.toast('Failed to start recording: ' + err.message, 'error');
      }
      this._resetMicButton(session);
    }
  }
  
  /**
   * Stop voice recording
   */
  _stopRecording() {
    const session = this._voiceSession;
    if (session?.phase !== 'recording') return;
    if (!this._voiceContextIsCurrent(session)) {
      this._resetMicButton(session);
      return;
    }
    this.isRecording = false;
    session.phase = 'transcribing';
    this.micBtn.classList.remove('recording', 'ready');
    this.micBtn.classList.add('processing');
    this.micBtn.title = 'Transcribing...';
    this.micBtn.setAttribute('aria-label', this.micBtn.title);
    this.micBtn.setAttribute('aria-pressed', 'false');
    this.micBtn.disabled = true;
    this._hideRecordingIndicator();
    this.updateSendButton();
    if (session.recorder.state !== 'inactive') session.recorder.stop();
  }
  
  /**
   * Discard this dictation while retaining the existing draft.
   */
  _cancelRecording({ silent = false } = {}) {
    if (!this._voiceSession) return;
    this._resetMicButton();
    if (!silent) Utils.toast('Dictation cancelled. Your draft is unchanged.', 'info');
  }
  
  /**
   * Process recorded audio - send to STT API
   */
  async _processRecording(session = this._voiceSession) {
    if (!session || !this._voiceContextIsCurrent(session)) {
      this._resetMicButton(session);
      return;
    }
    // A device can end recording itself, without a click on the mic.
    session.phase = 'transcribing';
    this.isRecording = false;
    this.micBtn.classList.remove('recording', 'ready');
    this.micBtn.classList.add('processing');
    this.micBtn.title = 'Transcribing...';
    this.micBtn.setAttribute('aria-label', this.micBtn.title);
    this.micBtn.setAttribute('aria-pressed', 'false');
    this.micBtn.disabled = true;
    this.updateSendButton();
    this._hideRecordingIndicator();

    if (session.chunks.length === 0) {
      this._resetMicButton(session);
      return;
    }

    const mimeType = session.recorder.mimeType || this._getSupportedMimeType();
    const audioBlob = new Blob(session.chunks, { type: mimeType });
    
    // Check minimum size (very short recordings won't have speech)
    if (audioBlob.size < 5000) {
      Utils.toast('Recording too short - speak longer before clicking again', 'warning');
      this._resetMicButton(session);
      return;
    }
    
    try {
      // Send to STT API
      const formData = new FormData();
      const extension = { 'audio/mp4': 'mp4', 'audio/ogg': 'ogg', 'audio/wav': 'wav' }[mimeType.split(';')[0]] || 'webm';
      formData.append('audio', audioBlob, `recording.${extension}`);
      formData.append('mode', session.mode);

      const response = await Utils.auth.fetch('/api/stt', {
        method: 'POST',
        body: formData,
        signal: session.controller.signal
      });
      const data = await response.json();
      if (!this._voiceContextIsCurrent(session)) return;
      const text = typeof data.text === 'string' ? data.text.trim() : '';
      if (response.ok && data.ok && text) {
        // Read the current draft so typing and corrections during STT survive.
        const draft = this.inputField.value;
        this.inputField.value = draft + (draft && !/\s$/.test(draft) ? ' ' : '') + text;
        this.inputField.focus();
        this.inputField.setSelectionRange(this.inputField.value.length, this.inputField.value.length);
        this.inputField.dispatchEvent(new Event('input', { bubbles: true }));
        Utils.toast('Dictation added. Review your message, then Send.', 'success', 3000);
      } else {
        Utils.toast(data.error || 'No speech detected. Your draft is unchanged.', 'error');
      }
    } catch (err) {
      if (this._voiceContextIsCurrent(session)) {
        Utils.toast('Could not transcribe audio. Your draft is unchanged.', 'error');
      }
    } finally {
      this._resetMicButton(session);
    }
  }
  
  /**
   * Reset mic button to default state
   */
  _resetMicButton(session = this._voiceSession) {
    if (!session || this._voiceSession !== session) return;
    this._voiceSession = null;
    session.controller.abort();
    if (session.recorder) {
      session.recorder.onstop = null;
      session.recorder.ondataavailable = null;
      session.recorder.onerror = null;
      if (session.recorder.state !== 'inactive') session.recorder.stop();
    }
    session.stream?.getTracks().forEach(track => track.stop());
    this.isRecording = false;
    this.micBtn.classList.remove('recording', 'processing', 'ready', 'preparing');
    this.micBtn.title = 'Dictate a message';
    this.micBtn.setAttribute('aria-label', this.micBtn.title);
    this.micBtn.setAttribute('aria-pressed', 'false');
    this.micBtn.disabled = false;
    this.audioChunks = [];
    this.mediaRecorder = null;
    this._recordingStream = null;
    this._hideRecordingIndicator();
    this.updateSendButton();
  }
  
  /**
   * Show recording indicator bar at top of page
   */
  _showRecordingIndicator() {
    if (this.recordingIndicator) return;
    
    this.recordingIndicator = document.createElement('div');
    this.recordingIndicator.className = 'recording-indicator';
    document.body.appendChild(this.recordingIndicator);
  }
  
  /**
   * Hide recording indicator
   */
  _hideRecordingIndicator() {
    if (this.recordingIndicator) {
      this.recordingIndicator.remove();
      this.recordingIndicator = null;
    }
  }
  
  /**
   * Get supported MIME type for MediaRecorder
   */
  _getSupportedMimeType() {
    const types = [
      'audio/webm;codecs=opus',
      'audio/webm',
      'audio/ogg;codecs=opus',
      'audio/mp4',
      'audio/wav'
    ];
    
    for (const type of types) {
      if (MediaRecorder.isTypeSupported(type)) {
        return type;
      }
    }
    
    return 'audio/webm'; // Default fallback
  }

  /**
   * Setup socket event listeners
   */
  _setupSocketListeners() {
    const socket = window.jarvisSocket;
    
    socket.on('thinking', (data) => {
      if (this._pendingSend?.requestId === data.message_id) this._pendingSend = null;
      this.currentMessageId = data.message_id;
      this._activatePendingToolsForMessage(data.message_id, true);
      this.isProcessing = true;
      this.updateSendButton();
      this._clearMessageResponseActions();
      this.showThinking();
    });
    
    socket.on('toolStart', (data) => {
      this._activatePendingToolsForMessage(data.message_id);
      this._markToolStarted(data);
      // Use call_index for unique card ID when same tool called multiple times
      const cardId = data.call_index > 0 ? `${data.tool}_${data.call_index}` : data.tool;
      this.addToolCard(cardId, data.tool, 'pending', data.args);
    });
    
    socket.on('toolProgress', (data) => {
      if (data.tool) {
        const cardId = data.call_index > 0 ? `${data.tool}_${data.call_index}` : data.tool;
        if (data.tool === 'opencode' && data.status) {
          this._updateOpenCodeProgressCard(cardId, data);
          this.showProgressStatus(data.status);
        } else {
          // Update specific tool card with progress
          this.updateToolCard(cardId, data.tool, 'pending', {
            progress: data.progress,
            status: data.status
          });
        }
      } else if (data.status) {
        // Show routing/progress status as ephemeral message
        this.showProgressStatus(data.status);
      }
    });
    
    socket.on('toolComplete', (data) => {
      this._activatePendingToolsForMessage(data.message_id);
      this._markToolFinished(data);
      // Use call_index or workflow_step for unique ID (allows duplicate tools)
      let cardId;
      if (data.call_index > 0) {
        cardId = `${data.tool}_${data.call_index}`;
      } else if (data.workflow_step != null) {
        cardId = `${data.tool}_step${data.workflow_step}`;
      } else {
        cardId = data.tool;
      }
      const status = data.skipped === true ? 'skipped' : 'success';
      const result = status === 'skipped'
        ? (data.reason || 'Condition evaluated to false')
        : data.result;
      this.updateToolCard(cardId, data.tool, status, result, data.duration_ms);
    });
    
    socket.on('toolError', (data) => {
      this._activatePendingToolsForMessage(data.message_id);
      this._markToolFinished(data);
      // Use call_index for unique card ID when same tool called multiple times
      const cardId = data.call_index > 0 ? `${data.tool}_${data.call_index}` : data.tool;
      this.updateToolCard(cardId, data.tool, 'error', { error: data.error });
    });

    socket.on('modeChanged', (data) => {
      this._cancelRecording({ silent: true });
      this.cancelAttachmentPreparation();
      this._handleImageAttachmentsForMode(data.mode);
    });

    socket.on('embeddingStatus', (data) => {
      if (!data?.message_id) return;
      if (data.conversation_id && data.conversation_id !== socket.conversationId) return;
      const notices = {
        fallback: 'Using a fallback embedding host; semantic search is working.',
        unavailable: 'Embeddings unavailable; semantic retrieval may be limited.'
      };
      const notice = notices[data.status];
      if (!notice) return;
      this._embeddingNotices ??= new Set();
      const key = `${data.conversation_id}:${data.message_id}:${data.status}`;
      if (this._embeddingNotices.has(key)) return;
      this._embeddingNotices.add(key);
      if (this._embeddingNotices.size > 100) {
        this._embeddingNotices.delete(this._embeddingNotices.values().next().value);
      }
      Utils.toast(notice, 'warning', 6000);
    });
    
    socket.on('response', (data) => {
      if (this._pendingSend?.requestId === data.message_id) this._pendingSend = null;
      this._activatePendingToolsForMessage(data.message_id);
      this.hideThinking();
      this.clearStatus();  // Clear any status messages
      this.pendingVisionRetryPayload = null;
      this.addAssistantMessage(data.text, data.tools_used, data);
      this.currentMessageId = null;
      this.isProcessing = false;
      this.updateSendButton();
      if (this._serverRunState?.message_id === data.message_id
          && ['running', 'stopping'].includes(this._serverRunState.status)) {
        this.restoreRunState(this._serverRunState, { fromSnapshot: true });
      }
      
      // Update token counter if usage data available
      if (data.usage) {
        this._updateTokenCounter(data.usage);
      }
      
      // Show discrete toast for provider-native/server-side tools.
      // Accept either the dedicated top-level field or the nested usage fallback.
      const serverSideTools = data.server_side_tools || data.usage?.server_side_tools || {};
      if (serverSideTools && typeof serverSideTools === 'object' && Object.keys(serverSideTools).length > 0) {
        const tools = Object.entries(serverSideTools)
          .filter(([, count]) => Number(count) > 0)
          .map(([name, count]) => {
            // Clean up tool name: SERVER_SIDE_TOOL_X_SEARCH -> X Search
            const cleanName = name.replace('SERVER_SIDE_TOOL_', '')
              .split('_')
              .map(word => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
              .join(' ');
            return `${cleanName}${count > 1 ? ` (${count}x)` : ''}`;
          })
          .join(', ');
        if (tools) {
          Utils.toast(`🔍 Server-side: ${tools}`, 'info', 4000);
        }
      }
    });
    
    socket.on('error', (data) => {
      this.hideThinking();
      this.clearStatus();
      this.addErrorMessage(data.error);
      this.rememberRenderedMessage('error', data.message_id);
      this._clearPendingToolsForMessage(data.message_id);
      if (
        ['vision_model_unsupported', 'vision_analysis_failed', 'image_edit_stash_failed', 'image_video_stash_failed', 'image_bundle_stash_failed'].includes(data.error_code)
        && this.pendingVisionRetryPayload
      ) {
        const retryPayload = this.pendingVisionRetryPayload;
        this.pendingVisionRetryPayload = null;
        if (!this._hasAttachedImages()) {
          this.attachedImages = retryPayload.images.map(({ url, filename }) => ({ url, filename }));
          this.imageAttachmentAction = retryPayload.action;
          this.imageAttachmentSettings = retryPayload.settings;
          this._renderImagePreviews();
          const retryMessage = data.error_code === 'image_edit_stash_failed'
            ? 'Image restored — retry the edit'
            : data.error_code === 'image_video_stash_failed'
              ? 'Image restored — retry video generation'
              : data.error_code === 'image_bundle_stash_failed'
                ? 'Images restored — retry preparing the attached sources'
                : 'Image restored — switch to a vision-capable model and resend';
          Utils.toast(retryMessage, 'info', 5000);
        }
      }
      this.currentMessageId = null;
      this.isProcessing = false;
      this.updateSendButton();
    });

    socket.on('cancelled', (data) => {
      this._resetProcessingUi();
      this._clearPendingToolsForMessage(data?.message_id);

      if (data?.message_id && this.currentMessageId === data.message_id) {
        this.currentMessageId = null;
      }

      Utils.toast('Stopped current task', 'info', 2500);
    });

    socket.on('cancelAck', (data) => {
      if (data?.message_id && this.currentMessageId === data.message_id) {
        if (data.status === 'not_running') {
          window.jarvisApp?.loadConversation(socket.conversationId);
        } else {
          this.showProgressStatus('Stopping…');
          this.stopBtn.disabled = true;
        }
      }
    });

    socket.on('runState', (data) => this.restoreRunState(data));
    socket.on('rejected', (data) => {
      socket.clearPendingRequest?.();
      const pending = this._pendingSend;
      if (pending?.requestId === data.message_id) {
        pending.element?.remove();
        this._renderedMessageIds?.delete(`user:${pending.requestId}`);
        const newerDraft = this.inputField.value;
        this.inputField.value = newerDraft && newerDraft !== pending.text
          ? `${pending.text}\n\n${newerDraft}` : pending.text;
        if (!this.attachedDocuments.length) this.attachedDocuments = pending.documents;
        if (!this.attachedImages.length) {
          this.attachedImages = pending.images;
          this.imageAttachmentAction = pending.imageAction;
          this.imageAttachmentSettings = pending.imageSettings;
        }
        if (!this.selectedToolHints.length) this.selectedToolHints = pending.toolHints || [];
        this._renderToolHintChips();
        this._renderDocumentPreviews();
        this._renderImagePreviews();
        Utils.autoResize(this.inputField);
        this._pendingSend = null;
      }
      this._resetProcessingUi();
      this.currentMessageId = null;
      Utils.toast(`${data.error} Your unsent draft is available below.`, 'warning', 6000);
      if (data.conversation_id) window.jarvisApp?.loadConversation(data.conversation_id, { reconcile: true });
    });
    socket.on('connectionChange', (data) => {
      this.updateSendButton();
      if (!data.connected && this.isProcessing) {
        this.showProgressStatus('Connection lost. Reconnecting to the task…');
        this.stopBtn.disabled = true;
      }
    });
    
    // Feedback events (async analysis after response)
    socket.on('feedbackStart', (data) => {
      this.pendingFeedback = { message_id: data.message_id, status: 'analyzing' };
      this._showFeedbackCard('analyzing', data.message_id);
    });
    
    socket.on('feedbackComplete', (data) => {
      this.pendingFeedback = null;
      this._updateFeedbackCard(data);
    });

    socket.on('completionGuardUpdated', (data) => {
      this._updateCompletionGuardCard(data);
    });

    socket.on('completionGuardTicketCreated', (data) => {
      this._updateCompletionGuardCard({
        ...data,
        status: 'ticket_created'
      });
      Utils.toast('Completion issue logged for follow-up', 'warning', 4000);
    });

    socket.on('completionGuardError', (data) => {
      const staleContext = /expired|not found|missing_session_context/i.test(data?.error || '');
      this._updateCompletionGuardCard({
        ...data,
        status: staleContext ? 'expired' : 'error'
      });
      if (!staleContext) {
        Utils.toast(data.error || 'Completion Guard failed', 'error', 4000);
      }
    });

    socket.on('messageReactionUpdated', (data) => {
      this._updateMessageReactionActions(data);
    });

    socket.on('messageReactionError', (data) => {
      this._handleMessageReactionError(data);
    });
  }

  /**
   * Setup file upload functionality (images + text files)
   */
  _setupImageUpload() {
    if (!this.uploadBtn || !this.fileInput) {
      console.warn('[Chat] File upload elements not found');
      return;
    }
    
    // Click upload button -> trigger file input
    this.uploadBtn.addEventListener('click', () => {
      this.fileInput.click();
    });
    
    // Handle file selection (routes by type)
    this.fileInput.addEventListener('change', async (e) => {
      const files = Array.from(e.target.files || []);
      if (files.length === 1) {
        await this.attachFile(files[0]);
      } else if (files.length > 1) {
        await this._attachMultipleFiles(files);
      }
      // Reset input so same file can be selected again
      this.fileInput.value = '';
    });
    
    if (this.clearAllImagesBtn) {
      this.clearAllImagesBtn.addEventListener('click', () => {
        this.clearAttachedImage();
      });
    }
    
    // Drag and drop supports the same bounded bundle as the picker.
    const container = document.querySelector('.chat-input-container');
    if (container) {
      container.addEventListener('dragover', (e) => {
        e.preventDefault();
        container.classList.add('drag-over');
      });
      
      container.addEventListener('dragleave', (e) => {
        e.preventDefault();
        container.classList.remove('drag-over');
      });
      
      container.addEventListener('drop', async (e) => {
        e.preventDefault();
        container.classList.remove('drag-over');
        
        const files = Array.from(e.dataTransfer.files || []);
        if (files.length === 1) {
          await this.attachFile(files[0]);
        } else if (files.length > 1) {
          await this._attachMultipleFiles(files);
        }
      });
    }
    
    // Paste image from clipboard (text paste goes to textarea normally)
    document.addEventListener('paste', async (e) => {
      const items = e.clipboardData?.items;
      if (!items) return;
      
      for (const item of items) {
        if (item.type.startsWith('image/')) {
          e.preventDefault();
          const file = item.getAsFile();
          if (file) {
            await this.attachImage(file);
          }
          break;
        }
      }
    });
    
    console.log('[Chat] File upload ready (images + text)');
  }
  
  /**
   * Setup image action modal (Analyze / Video / Image)
   */
  _setupImageActionModal() {
    if (!this.imageActionModal) {
      console.warn('[Chat] Image action modal not found');
      return;
    }
    
    // Close button
    const closeBtn = document.getElementById('closeImageActionModal');
    if (closeBtn) {
      closeBtn.addEventListener('click', () => this._hideImageActionModal());
    }
    
    // Cancel button
    const cancelBtn = document.getElementById('cancelImageAction');
    if (cancelBtn) {
      cancelBtn.addEventListener('click', () => this._hideImageActionModal());
    }
    
    // Confirm button
    const confirmBtn = document.getElementById('confirmImageAction');
    if (confirmBtn) {
      confirmBtn.addEventListener('click', () => this._confirmImageAction());
    }
    
    // Close on overlay click
    this.imageActionModal.addEventListener('click', (e) => {
      if (e.target === this.imageActionModal) {
        this._hideImageActionModal();
      }
    });
    
    // Radio button change -> show/hide option panels
    const radios = this.imageActionModal.querySelectorAll('input[name="imageAction"]');
    radios.forEach(radio => {
      radio.addEventListener('change', () => this._updateImageActionOptions());
    });
    
    // Image provider change -> show/hide provider-specific options
    const imageProviderSelect = document.getElementById('imgActionImageProvider');
    if (imageProviderSelect) {
      imageProviderSelect.addEventListener('change', () => this._updateImageProviderOptions(true));
    }
    document.getElementById('imgActionImageModel')?.addEventListener(
      'change', () => this._updateImageProviderOptions()
    );

    const videoProviderSelect = document.getElementById('imgActionVideoProvider');
    if (videoProviderSelect) {
      videoProviderSelect.addEventListener('change', () => this._updateVideoProviderOptions(true));
    }
    document.getElementById('imgActionVideoModel')?.addEventListener(
      'change', () => this._updateVideoProviderOptions()
    );
    document.getElementById('imgActionVideoDuration')?.addEventListener(
      'change', () => this._updateVideoProviderOptions()
    );
    document.getElementById('imgActionVideoResolution')?.addEventListener(
      'change', () => this._updateVideoProviderOptions()
    );
    
    console.log('[Chat] Image action modal ready');
  }
  
  /**
   * Show the image action modal with preview
   */
  async _showImageActionModal(uploadDataOrArray, preferredAction = 'analyze', context = this._attachmentContext()) {
    if (!this.imageActionModal) return;

    try {
      await window.jarvisApp?._ensureSettingsData?.(window.jarvisSocket?.mode || 'cloud');
    } catch (error) {
      console.warn('[Chat] Could not refresh media model settings:', error);
    }
    if (!this._attachmentContextIsCurrent(context)) return;
    
    const uploads = Array.isArray(uploadDataOrArray) ? uploadDataOrArray : [uploadDataOrArray];
    this.pendingImageBatch = uploads;
    
    // Show image preview(s) — order in batch = upload order (first is used for Video/Image)
    if (this.imageActionPreview) {
      this.imageActionPreview.innerHTML = '';
      uploads.forEach((uploadData, index) => {
        const item = document.createElement('div');
        item.className = 'image-action-preview-item';
        item.dataset.index = String(index);

        const img = document.createElement('img');
        img.src = uploadData.url;
        img.alt = `Upload ${index + 1}`;
        item.appendChild(img);

        if (index === 0) {
          const badge = document.createElement('span');
          badge.className = 'image-action-preview-primary';
          badge.textContent = '1st';
          item.appendChild(badge);
        }

        this.imageActionPreview.appendChild(item);
      });
    }
    
    const allowedActions = new Set(['analyze', 'video', 'image']);
    const selectedAction = allowedActions.has(preferredAction) ? preferredAction : 'analyze';
    const selectedRadio = this.imageActionModal.querySelector(
      `input[name="imageAction"][value="${selectedAction}"]`
    );
    if (selectedRadio) selectedRadio.checked = true;

    this._resetImageActionOptions();
    this._updateImageActionOptions();
    
    // Show modal
    this.imageActionModal.classList.add('active');
  }

  async attachImportedImage(uploadData, preferredAction = 'analyze') {
    if (!uploadData?.ok || !uploadData.url || !uploadData.filename) {
      throw new Error('Jarvis Web received an invalid image handoff');
    }

    if (this.isProcessing || this.attachedDocuments.length || this.attachedImages.length || this.pendingImageFiles?.length || this._imageUpload || this._attachmentSend) {
      throw new Error('Remove the current attachments before importing a reference image.');
    }
    const context = this._attachmentContext();
    this._imageUpload = context;
    try {
      await this._showImageActionModal(uploadData, preferredAction, context);
    } finally {
      if (this._imageUpload === context) this._imageUpload = null;
    }
  }
  
  /**
   * Hide the image action modal
   */
  _hideImageActionModal() {
    if (this.imageActionModal) {
      this.imageActionModal.classList.remove('active');
    }
    this.pendingImageBatch = null;
  }
  
  /**
   * Update which option panel is visible based on selected action
   */
  _updateImageActionOptions() {
    const selected = this.imageActionModal?.querySelector('input[name="imageAction"]:checked')?.value || 'analyze';
    
    const videoOpts = document.getElementById('imageActionVideoOpts');
    const imageOpts = document.getElementById('imageActionImageOpts');
    
    if (videoOpts) videoOpts.style.display = selected === 'video' ? 'block' : 'none';
    if (imageOpts) imageOpts.style.display = selected === 'image' ? 'block' : 'none';
    
    this._updateImageActionPreviewHighlight(selected);

    // Update provider-specific options if image panel is now visible
    if (selected === 'image') {
      this._updateImageProviderOptions();
    } else if (selected === 'video') {
      this._updateVideoProviderOptions();
    }
  }

  /**
   * Grey out non-first modal previews when Video/Image only uses the first upload.
   */
  _updateImageActionPreviewHighlight(selectedAction = null) {
    const selected = selectedAction
      || this.imageActionModal?.querySelector('input[name="imageAction"]:checked')?.value
      || 'analyze';
    const singleOnly = selected === 'video' || selected === 'image';
    const items = this.imageActionPreview?.querySelectorAll('.image-action-preview-item') || [];

    items.forEach((item, index) => {
      item.classList.toggle('is-unused', singleOnly && index > 0);
      item.classList.toggle('is-primary', singleOnly && index === 0);

      const badge = item.querySelector('.image-action-preview-primary');
      if (badge) {
        badge.textContent = singleOnly ? 'Used' : '1st';
      }
    });
  }
  
  /**
   * Populate a request-scoped image/video model selector from the shared catalog.
   */
  _populateImageActionModel(mediaType, resetModel = false) {
    const title = mediaType === 'image' ? 'Image' : 'Video';
    const provider = document.getElementById(`imgAction${title}Provider`)?.value;
    const select = document.getElementById(`imgAction${title}Model`);
    const providerMetadata = window.jarvisApp?._settingsData?.[`${mediaType}_providers`]?.[provider];
    const models = Array.isArray(providerMetadata?.models) ? providerMetadata.models : [];
    if (!select) return { providerMetadata, modelMetadata: null };

    const previous = select.value;
    select.replaceChildren();
    for (const model of models) {
      if (!model?.id) continue;
      select.add(new Option(model.name || model.id, model.id));
    }

    const available = models.map(model => model.id);
    const effectiveModel = providerMetadata?.model;
    const selected = !resetModel && available.includes(previous)
      ? previous
      : available.includes(effectiveModel)
        ? effectiveModel
        : available[0] || effectiveModel || '';
    if (selected && !available.includes(selected)) {
      select.add(new Option(selected, selected));
    }
    select.value = selected;
    return {
      providerMetadata,
      modelMetadata: models.find(model => model.id === selected) || providerMetadata,
    };
  }

  /**
   * Show/hide provider-specific options for Image to Image
   */
  _updateImageProviderOptions(resetModel = false) {
    const provider = document.getElementById('imgActionImageProvider')?.value || 'gemini';
    
    const geminiOpts = document.getElementById('imgActionGeminiOpts');
    const openaiOpts = document.getElementById('imgActionOpenaiOpts');
    const xaiOpts = document.getElementById('imgActionXaiOpts');
    
    if (geminiOpts) geminiOpts.style.display = provider === 'gemini' ? 'block' : 'none';
    if (openaiOpts) openaiOpts.style.display = provider === 'openai' ? 'block' : 'none';
    if (xaiOpts) xaiOpts.style.display = provider === 'xai' ? 'block' : 'none';

    const { providerMetadata, modelMetadata } = this._populateImageActionModel('image', resetModel);
    const selectedModel = document.getElementById('imgActionImageModel')?.value
      || providerMetadata?.model || '';
    const selectedCapabilities = Array.isArray(modelMetadata?.capabilities)
      ? modelMetadata.capabilities
      : [];
    const transparent = document.getElementById('imgActionTransparent');
    const transparentDesc = document.getElementById('imgActionTransparentDesc');
    const modelDesc = document.getElementById('imgActionImageModelDesc');
    const isGptImage2 = /^gpt-image-2(?:$|-)/.test(String(selectedModel));
    const supportsTransparent = selectedCapabilities.includes('transparent_background')
      || (selectedCapabilities.length === 0 && !isGptImage2);
    if (modelDesc) {
      const selectedName = modelMetadata?.name || selectedModel;
      modelDesc.textContent = selectedName ? `Selected model: ${selectedName}` : '';
    }

    const imageSize = document.getElementById('imgActionImageSize');
    const catalogImageSizes = Array.isArray(modelMetadata?.resolutions)
      ? modelMetadata.resolutions.filter(value => /^\d+(?:\.\d+)?K$/i.test(String(value)))
      : [];
    const imageSizes = catalogImageSizes.length ? catalogImageSizes : ['1K', '2K', '4K'];
    if (imageSize) {
      const previous = imageSize.value;
      imageSize.replaceChildren();
      for (const size of imageSizes) {
        imageSize.add(new Option(`${size}${size === '2K' ? ' (Default)' : ''}`, size));
      }
      imageSize.value = imageSizes.includes(previous)
        ? previous
        : (imageSizes.includes('2K') ? '2K' : imageSizes[0]);
    }
    if (transparent) {
      transparent.disabled = provider === 'openai' && !supportsTransparent;
      if (transparent.disabled) transparent.checked = false;
    }
    if (transparentDesc) {
      transparentDesc.textContent = supportsTransparent
        ? 'For logos, sprites, overlays (png/webp)'
        : `${selectedModel} does not support transparent backgrounds`;
    }
  }

  /**
   * Populate video resolutions from the effective model in the shared catalog.
   */
  _updateVideoProviderOptions(resetModel = false) {
    const provider = document.getElementById('imgActionVideoProvider')?.value || 'xai';
    const select = document.getElementById('imgActionVideoResolution');
    const { modelMetadata } = this._populateImageActionModel('video', resetModel);
    const resolutions = Array.isArray(modelMetadata?.resolutions) && modelMetadata.resolutions.length
      ? modelMetadata.resolutions
      : (provider === 'gemini' ? ['720p', '1080p', '4k'] : ['720p', '480p']);
    const modelDesc = document.getElementById('imgActionVideoModelDesc');
    if (modelDesc) {
      const selectedModel = document.getElementById('imgActionVideoModel')?.value;
      modelDesc.textContent = selectedModel
        ? `Selected model: ${modelMetadata?.name || selectedModel}`
        : '';
    }

    const ratioSelect = document.getElementById('imgActionVideoRatio');
    const catalogAspectRatios = Array.isArray(modelMetadata?.aspect_ratios)
      ? modelMetadata.aspect_ratios
      : [];
    const aspectRatios = catalogAspectRatios.length
      ? catalogAspectRatios
      : (provider === 'gemini'
        ? ['16:9', '9:16']
        : ['16:9', '4:3', '1:1', '9:16', '3:4', '3:2', '2:3']);
    if (ratioSelect) {
      const previous = ratioSelect.value;
      const ratioLabels = {
        '16:9': '16:9 (Widescreen)',
        '9:16': '9:16 (Vertical)',
        '3:4': '3:4 (Portrait)',
        '4:3': '4:3 (Classic TV)',
        '1:1': '1:1 (Square)',
        '3:2': '3:2 (Photo)',
        '2:3': '2:3 (Tall Portrait)',
      };
      ratioSelect.replaceChildren();
      for (const ratio of aspectRatios) {
        ratioSelect.add(new Option(ratioLabels[ratio] || ratio, ratio));
      }
      ratioSelect.value = aspectRatios.includes(previous)
        ? previous
        : (aspectRatios.includes('16:9') ? '16:9' : aspectRatios[0]);
    }

    if (select && Array.isArray(resolutions) && resolutions.length) {
      const previous = select.value;
      select.replaceChildren();
      resolutions.forEach((resolution) => {
        const option = document.createElement('option');
        option.value = resolution;
        const normalized = String(resolution).toLowerCase();
        const label = normalized === '4k'
          ? '4K (Ultra HD)'
          : normalized === '1080p'
            ? '1080p (Full HD)'
            : normalized === '720p'
              ? '720p (HD)'
              : normalized === '480p'
                ? '480p (SD)'
                : resolution;
        option.textContent = label;
        select.appendChild(option);
      });

      select.value = resolutions.includes(previous)
        ? previous
        : (resolutions.includes('720p') ? '720p' : resolutions[0]);
    }

    // Resolution must be final before applying duration-by-resolution rules.
    const durationInput = document.getElementById('imgActionVideoDuration');
    const durationDesc = document.getElementById('imgActionVideoDurationDesc');
    const durationRules = modelMetadata?.duration_seconds
      || (provider === 'gemini' ? { values: [4, 6, 8] } : { min: 1, max: 15 });
    const resolutionDurationValues = durationRules.by_resolution?.[select?.value];
    const allowedDurationValues = Array.isArray(resolutionDurationValues)
      ? resolutionDurationValues
      : durationRules.values;
    const durationValues = Array.isArray(allowedDurationValues)
      ? allowedDurationValues.map(Number).filter(Number.isFinite).sort((a, b) => a - b)
      : [];
    if (durationInput && durationValues.length) {
      const requested = Number.parseInt(durationInput.value, 10);
      const nearest = durationValues.reduce((best, value) => (
        Math.abs(value - requested) < Math.abs(best - requested) ? value : best
      ), durationValues[0]);
      durationInput.min = String(durationValues[0]);
      durationInput.max = String(durationValues[durationValues.length - 1]);
      durationInput.step = durationValues.length > 1
        ? String(durationValues[1] - durationValues[0])
        : '1';
      durationInput.value = String(nearest);
      if (durationDesc) durationDesc.textContent = `Allowed: ${durationValues.join(', ')} seconds`;
    } else if (durationInput && Number.isFinite(Number(durationRules.min)) && Number.isFinite(Number(durationRules.max))) {
      const minimum = Number(durationRules.min);
      const maximum = Number(durationRules.max);
      const requested = Number.parseInt(durationInput.value, 10);
      const clamped = Number.isFinite(requested)
        ? Math.max(minimum, Math.min(maximum, requested))
        : minimum;
      durationInput.min = String(minimum);
      durationInput.max = String(maximum);
      durationInput.step = '1';
      durationInput.value = String(clamped);
      if (durationDesc) durationDesc.textContent = `${minimum}-${maximum} seconds`;
    }
  }
  
  /**
   * Effective image/video provider from AI config (env + web override), for modal defaults.
   */
  _getEffectiveImageProvider() {
    const select = document.getElementById('setting-image-provider');
    if (select?.value && ['gemini', 'openai', 'xai'].includes(select.value)) {
      return select.value;
    }
    const value = window.jarvisApp?._settingsData?.image?.provider?.value;
    return ['gemini', 'openai', 'xai'].includes(value) ? value : 'gemini';
  }

  _getEffectiveVideoProvider() {
    const select = document.getElementById('setting-video-provider');
    if (select?.value && ['xai', 'gemini'].includes(select.value)) {
      return select.value;
    }
    const value = window.jarvisApp?._settingsData?.video?.provider?.value;
    return ['xai', 'gemini'].includes(value) ? value : 'xai';
  }

  /**
   * Disable modal provider options whose API keys are not configured
   * (uses provider_availability from the cached settings payload).
   */
  _applyMediaProviderAvailability(select, domain) {
    const availability = window.jarvisApp?._settingsData?.provider_availability?.[domain];
    if (!select || !availability) return;
    Array.from(select.options).forEach((option) => {
      if (!option.value) return;
      if (option.dataset.availAnnotated === '1' && option.dataset.baseLabel) {
        option.textContent = option.dataset.baseLabel;
      }
      option.dataset.baseLabel = option.textContent;
      delete option.dataset.availAnnotated;
      const entry = availability[option.value];
      if (entry?.status === 'unavailable') {
        // Keep native dropdown text short; option rows do not wrap reliably
        // on narrow/mobile browsers.
        option.textContent = entry.reason || 'Provider not configured';
        option.dataset.availAnnotated = '1';
        option.disabled = option.value !== select.value;
      } else {
        option.disabled = false;
      }
    });
  }

  /**
   * Reset all image action options to defaults
   */
  _resetImageActionOptions() {
    // Video options
    const videoProvider = document.getElementById('imgActionVideoProvider');
    const videoRatio = document.getElementById('imgActionVideoRatio');
    const videoDuration = document.getElementById('imgActionVideoDuration');
    const videoResolution = document.getElementById('imgActionVideoResolution');
    if (videoProvider) videoProvider.value = this._getEffectiveVideoProvider();
    if (videoRatio) videoRatio.value = '16:9';
    if (videoDuration) videoDuration.value = '5';
    this._updateVideoProviderOptions(true);
    this._applyMediaProviderAvailability(videoProvider, 'video');
    if (videoResolution && [...videoResolution.options].some(option => option.value === '720p')) {
      videoResolution.value = '720p';
      // Restore the intended reset duration before applying the now-final
      // resolution's duration constraints.
      if (videoDuration) videoDuration.value = '5';
      this._updateVideoProviderOptions();
    }
    
    // Image options
    const imageProvider = document.getElementById('imgActionImageProvider');
    const imageRatio = document.getElementById('imgActionImageRatio');
    const imageSize = document.getElementById('imgActionImageSize');
    const imageStyle = document.getElementById('imgActionImageStyle');
    if (imageProvider) imageProvider.value = this._getEffectiveImageProvider();
    this._applyMediaProviderAvailability(imageProvider, 'image');
    if (imageRatio) imageRatio.value = '';
    if (imageSize) imageSize.value = '2K';
    if (imageStyle) imageStyle.value = '';
    
    // Gemini options
    const grounding = document.getElementById('imgActionGrounding');
    const negPrompt = document.getElementById('imgActionNegPrompt');
    if (grounding) grounding.checked = false;
    if (negPrompt) negPrompt.value = '';
    
    // OpenAI options
    const transparent = document.getElementById('imgActionTransparent');
    const outputFormat = document.getElementById('imgActionOutputFormat');
    if (transparent) transparent.checked = false;
    if (outputFormat) outputFormat.value = 'png';
    
    // xAI options
    const count = document.getElementById('imgActionCount');
    if (count) count.value = '1';
    
    // Reset provider-specific visibility
    this._updateImageProviderOptions(true);
  }
  
  /**
   * Collect settings from the image action modal based on selected action
   */
  _collectImageActionSettings() {
    const action = this.imageActionModal?.querySelector('input[name="imageAction"]:checked')?.value || 'analyze';
    const settings = {};
    
    if (action === 'video') {
      this._updateVideoProviderOptions();
      settings.aspect_ratio = document.getElementById('imgActionVideoRatio')?.value || '16:9';
      settings.duration = parseInt(document.getElementById('imgActionVideoDuration')?.value) || 5;
      settings.resolution = document.getElementById('imgActionVideoResolution')?.value || '720p';
      settings.provider = document.getElementById('imgActionVideoProvider')?.value || 'xai';
      settings.model = document.getElementById('imgActionVideoModel')?.value || undefined;
    } else if (action === 'image') {
      const provider = document.getElementById('imgActionImageProvider')?.value || 'gemini';
      settings.provider = provider;
      settings.model = document.getElementById('imgActionImageModel')?.value || undefined;
      
      const ratio = document.getElementById('imgActionImageRatio')?.value;
      if (ratio) settings.aspect_ratio = ratio;
      
      settings.image_size = document.getElementById('imgActionImageSize')?.value || '2K';
      
      const style = document.getElementById('imgActionImageStyle')?.value?.trim();
      if (style) settings.style = style;
      
      // Provider-specific settings (only collect from the active provider)
      if (provider === 'gemini') {
        const grounding = document.getElementById('imgActionGrounding')?.checked;
        if (grounding) settings.use_grounding = true;
        const negPrompt = document.getElementById('imgActionNegPrompt')?.value?.trim();
        if (negPrompt) settings.negative_prompt = negPrompt;
      } else if (provider === 'openai') {
        const transparentInput = document.getElementById('imgActionTransparent');
        const transparent = transparentInput?.checked && !transparentInput?.disabled;
        if (transparent) settings.transparent = true;
        const outputFormat = document.getElementById('imgActionOutputFormat')?.value;
        if (outputFormat) settings.output_format = outputFormat;
      } else if (provider === 'xai') {
        const count = parseInt(document.getElementById('imgActionCount')?.value);
        if (count && count > 1) settings.n = count;
      }
    }
    // For 'analyze', settings stays empty (current behavior)
    
    return { action, settings };
  }
  
  /**
   * Confirm the image action and attach image with settings
   */
  _confirmImageAction() {
    if (this._conversationLoadPending) return;
    if (!this.pendingImageBatch?.length) return;
    
    const { action, settings } = this._collectImageActionSettings();
    const batch = this.pendingImageBatch;
    
    if (action === 'video' || action === 'image') {
      if (batch.length !== 1 || this.attachedImages.length || this.attachedDocuments.length) {
        Utils.toast('Image editing and video generation require one reference image only. Choose Analyze for multiple sources.', 'error', 5000);
        return;
      }
    }
    if (batch.length + this.attachedImages.length + this.attachedDocuments.length > this._getMaxImages()) {
      Utils.toast(`Maximum ${this._getMaxImages()} sources in this mode. Remove sources before adding these images.`, 'error');
      return;
    }
    
    this.imageAttachmentAction = action;
    this.imageAttachmentSettings = settings;
    
    batch.forEach((uploadData) => {
      this.attachedImages.push({
        url: uploadData.url,
        filename: uploadData.filename
      });
    });

    this._clearPendingImageFiles();
    this._renderImagePreviews();
    this._hideImageActionModal();
    this.inputField.focus();
    
    const actionLabels = { analyze: 'Analyze', video: 'Video', image: 'Image' };
    const countLabel = batch.length > 1 ? `${batch.length} images` : 'Image';
    Utils.toast(`${countLabel} attached: ${actionLabels[action] || action}`, 'success', 1500);
  }
  
  _getMaxImages() {
    const mode = window.jarvisSocket?.mode || 'cloud';
    return mode === 'local' ? 2 : 6;
  }
      
  _hasAttachedImages() {
    return this.attachedImages.length > 0;
  }
      
  _canAppendWithoutModal() {
    return this._hasAttachedImages()
      && this.imageAttachmentAction === 'analyze'
      && this.attachedImages.length < this._getMaxImages();
  }

  _getImageAttachmentPayload() {
    if (!this.attachedImages.length) return null;
    return {
      action: this.imageAttachmentAction,
      settings: { ...this.imageAttachmentSettings },
      images: this.attachedImages.map(({ url, filename }) => ({ url, filename }))
    };
  }

  _normalizeMessageImages(imageData) {
    if (!imageData) return [];
    if (Array.isArray(imageData)) return imageData.filter((img) => img?.url);
    if (Array.isArray(imageData.images)) return imageData.images.filter((img) => img?.url);
    if (imageData.url) return [imageData];
    return [];
  }

  _buildActionBadgeText(action, settings) {
    if (action === 'video') {
      return `VIDEO ${settings.aspect_ratio || ''} ${settings.duration || 5}s`;
    }
    if (action === 'image') {
      return `IMAGE ${settings.provider || ''}`;
    }
    return 'ANALYZE';
  }

  _renderImagePreviews() {
    const strip = this.imagePreviewStrip;
    const container = this.imagePreviewContainer;
    if (!strip || !container) return;

    strip.innerHTML = '';

    const pending = this.pendingImageFiles || [];
    if (!this.attachedImages.length && !pending.length) {
      container.style.display = 'none';
      if (this.imageActionBadge) {
        this.imageActionBadge.textContent = '';
      }
      return;
    }

    container.style.display = 'block';

    const previews = [
      ...this.attachedImages,
      ...pending.map(item => ({ url: item.previewUrl, filename: item.file.name, pending: item }))
    ];
    previews.forEach((img, index) => {
      const thumb = document.createElement('div');
      thumb.className = 'image-preview-thumb';

      const imageEl = document.createElement('img');
      imageEl.src = img.url;
      imageEl.alt = `Image ${index + 1}: ${img.filename || 'attached image'}`;
      imageEl.title = imageEl.alt;
      thumb.appendChild(imageEl);
      const label = document.createElement('span');
      label.className = 'attachment-image-label';
      label.textContent = `Image ${index + 1}${img.pending ? ' · Pending' : ''}`;
      thumb.appendChild(label);

      const removeBtn = document.createElement('button');
      removeBtn.type = 'button';
      removeBtn.className = 'remove-image-btn';
      removeBtn.title = 'Remove image';
      removeBtn.textContent = '×';
      removeBtn.disabled = Boolean(this._attachmentSend || this._imageUpload);
      removeBtn.addEventListener('click', () => img.pending
        ? this._removePendingImage(img.pending)
        : this._removeAttachedImageAt(index));
      thumb.appendChild(removeBtn);

      strip.appendChild(thumb);
    });

    if (pending.length && !this._imageUpload) {
      const retry = document.createElement('button');
      retry.type = 'button';
      retry.className = 'btn btn-secondary';
      retry.textContent = 'Retry image upload';
      retry.addEventListener('click', () => this._retryPendingImages());
      strip.appendChild(retry);
    }
    if (this.imageActionBadge) {
      const badgeText = this._buildActionBadgeText(this.imageAttachmentAction, this.imageAttachmentSettings);
      const countSuffix = this.attachedImages.length > 1 ? ` (${this.attachedImages.length})` : '';
      this.imageActionBadge.textContent = `${badgeText}${countSuffix}`;
    }
  }

  _removeAttachedImageAt(index) {
    if (this._attachmentSend || this._imageUpload) return;
    if (index < 0 || index >= this.attachedImages.length) return;
    this.attachedImages.splice(index, 1);
    if (!this.attachedImages.length) {
      this.imageAttachmentAction = 'analyze';
      this.imageAttachmentSettings = {};
    }
    this._renderImagePreviews();
  }

  _handleImageAttachmentsForMode(mode, options = {}) {
    const limit = mode === 'local' ? 2 : 6;
    if (this.attachedImages.length + this.attachedDocuments.length + (this.pendingImageFiles?.length || 0) > limit && options.toast !== false) {
      Utils.toast(`This draft has more than ${limit} sources. Remove sources or switch back before sending.`, 'warning', 5000);
    }
  }

  _attachmentContext() {
    return {
      epoch: this._attachmentEpoch,
      mode: window.jarvisSocket?.mode || 'cloud',
      conversationId: window.jarvisSocket?.conversationId || null,
      controller: new AbortController()
    };
  }

  _attachmentContextIsCurrent(context) {
    return context.epoch === this._attachmentEpoch
      && !context.controller.signal.aborted
      && context.mode === (window.jarvisSocket?.mode || 'cloud')
      && context.conversationId === (window.jarvisSocket?.conversationId || null);
  }

  cancelAttachmentPreparation({ preserveModal = false } = {}) {
    this._attachmentEpoch += 1;
    const wasPreparing = Boolean(this._attachmentSend || this._imageUpload);
    this._attachmentSend?.controller.abort();
    this._imageUpload?.controller.abort();
    this._attachmentSend = null;
    this._imageUpload = null;
    if (!preserveModal) this._hideImageActionModal();
    if (wasPreparing) {
      this.isProcessing = false;
      this.hideThinking();
      this.clearStatus();
      this.updateSendButton();
      this._renderDocumentPreviews();
      this._renderImagePreviews();
    }
    return wasPreparing;
  }

  setConversationLoading(loading, { preservePreparation = false } = {}) {
    if (loading) this._cancelRecording({ silent: true });
    if (loading && !preservePreparation) this.cancelAttachmentPreparation({ preserveModal: true });
    this._conversationLoadPending = Boolean(loading);
    this.updateSendButton();
  }

  _attachmentKind(file) {
    if (String(file?.type || '').startsWith('image/')) return 'image';
    if (this._isPdfFile(file)) return 'pdf';
    if (this._isVideoFile(file)) return 'video';
    if (this._isAudioFile(file)) return 'audio';
    const extension = String(file?.name || '').split('.').pop().toLowerCase();
    if (['txt', 'md'].includes(extension)) return 'text';
    return null;
  }

  _validateAttachmentSelection(files) {
    if (this._talkActive) return 'End Talk before attaching files.';
    if (this._conversationLoadPending) return 'Wait for the conversation to finish loading.';
    if (this._attachmentSend || this._imageUpload || this.pendingImageBatch?.length) {
      return 'Finish or cancel the current attachment preparation first.';
    }
    if (this.pendingImageFiles?.length) return 'Retry or remove the pending images before adding sources or sending.';
    if (files.length && this.isProcessing) return 'Wait for the current request to finish before attaching sources.';
    const total = this.attachedImages.length + this.attachedDocuments.length + files.length;
    if (total > this._getMaxImages()) {
      return `Maximum ${this._getMaxImages()} sources in ${window.jarvisSocket?.mode || 'cloud'} mode. No files were added.`;
    }
    if (files.length && this._hasAttachedImages() && this.imageAttachmentAction !== 'analyze') {
      return 'Image editing and video generation use one reference image. Remove it before attaching more sources.';
    }
    let textBytes = this.attachedDocuments.filter(item => item.kind === 'text')
      .reduce((sum, item) => sum + item.file.size, 0);
    for (const file of files) {
      const kind = this._attachmentKind(file);
      if (!kind) return `Unsupported file: ${file.name}. Use images, video, audio, PDF, .md, or .txt files.`;
      if (kind === 'pdf' && !String(file.name).toLowerCase().endsWith('.pdf')) {
        return 'Select PDF files with a .pdf extension.';
      }
      const limit = kind === 'image' ? 30 * 1024 * 1024 : kind === 'pdf' ? 50 * 1024 * 1024 : kind === 'text' ? 100 * 1024 : null;
      if (limit && file.size > limit) return `${file.name} is too large (max ${kind === 'text' ? '100KB' : `${limit / 1024 / 1024}MB`}).`;
      if (kind === 'text') textBytes += file.size;
    }
    if (textBytes > 100 * 1024) return 'Attached text files exceed the combined 100KB limit.';
    return null;
  }

  async _uploadImageFiles(files, context) {
    const formData = new FormData();
    files.forEach((file) => formData.append('images', file));
    formData.append('mode', context.mode);
    formData.append('include_base64', 'false');
    formData.append('current_image_count', String(this.attachedImages.length));
    const response = await fetch('/api/upload-images', {
      method: 'POST', body: formData, signal: context.controller.signal
    });
    const data = await response.json();
    if (!response.ok || !data.ok || !Array.isArray(data.images) || data.images.length !== files.length || data.errors?.length) {
      throw new Error(data.errors?.join('; ') || data.error || 'Image upload was incomplete. Use Retry image upload.');
    }
    return data.images;
  }

  _appendAnalyzeImages(uploadResults) {
    uploadResults.forEach((uploadData) => {
      this.attachedImages.push({ url: uploadData.url, filename: uploadData.filename });
    });
    this.imageAttachmentAction = 'analyze';
    this.imageAttachmentSettings = {};
    this._renderImagePreviews();
  }

  async attachImageFiles(files) {
    return this._attachMultipleFiles(Array.from(files));
  }

  async _attachMultipleFiles(files) {
    if (!files.length) return;
    const error = this._validateAttachmentSelection(files);
    if (error) {
      Utils.toast(error, 'error', 4000);
      return;
    }
    const imageFiles = [];
    for (const file of files) {
      const kind = this._attachmentKind(file);
      if (kind === 'image') {
        imageFiles.push(file);
      } else {
        this.attachedDocuments.push({ kind, file, uploadId: this._createArtifactUploadId(), attachment: null, previewUrl: null });
      }
    }
    this._renderDocumentPreviews();
    if (!imageFiles.length) return;

    this.pendingImageFiles = imageFiles.map(file => ({
      file, previewUrl: window.URL?.createObjectURL?.(file) || ''
    }));
    await this._retryPendingImages();
  }

  _clearPendingImageFiles() {
    (this.pendingImageFiles || []).forEach(item => {
      if (item.previewUrl) window.URL?.revokeObjectURL(item.previewUrl);
    });
    this.pendingImageFiles = [];
  }

  _removePendingImage(item) {
    if (this._imageUpload || this._attachmentSend) return;
    this._hideImageActionModal();
    if (item.previewUrl) window.URL?.revokeObjectURL(item.previewUrl);
    this.pendingImageFiles = this.pendingImageFiles.filter(candidate => candidate !== item);
    this._renderImagePreviews();
  }

  async _retryPendingImages() {
    if (this._conversationLoadPending) {
      Utils.toast('Wait for the conversation to finish loading.', 'info');
      return;
    }
    if (!this.pendingImageFiles?.length || this.isProcessing || this.pendingImageBatch?.length) return;
    if (this.attachedImages.length + this.attachedDocuments.length + this.pendingImageFiles.length > this._getMaxImages()) {
      Utils.toast(`Maximum ${this._getMaxImages()} sources in this mode. Remove sources before retrying.`, 'error');
      return;
    }
    const imageFiles = this.pendingImageFiles.map(item => item.file);
    const context = this._attachmentContext();
    this._imageUpload = context;
    this.isProcessing = true;
    this.updateSendButton();
    this.showThinking();
    this.showProgressStatus('Uploading images…');
    this._renderImagePreviews();
    try {
      const uploads = await this._uploadImageFiles(imageFiles, context);
      if (!this._attachmentContextIsCurrent(context)) return;
      if (this.attachedDocuments.length || this._canAppendWithoutModal()) {
        this._clearPendingImageFiles();
        this._appendAnalyzeImages(uploads);
      } else {
        // Keep browser Files until the action is confirmed. Model settings can
        // still be loading when Stop or a mode change dismisses this modal.
        await this._showImageActionModal(uploads, 'analyze', context);
      }
    } catch (err) {
      if (this._attachmentContextIsCurrent(context)) {
        Utils.toast(`${err.message || 'Image upload failed.'} Your selected images are ready to retry.`, 'error', 5000);
      }
    } finally {
      if (this._imageUpload === context) {
        this._imageUpload = null;
        this.isProcessing = false;
        this.hideThinking();
        this.clearStatus();
        this.updateSendButton();
        this._renderImagePreviews();
      }
    }
  }

  /**
   * Setup file conversion functionality (bypasses vision analysis)
   */
  _setupFileConversion() {
    if (!this.convertBtn || !this.convertInput) {
      console.warn('[Chat] File conversion elements not found');
      return;
    }
    
    // Click convert button -> trigger file input
    this.convertBtn.addEventListener('click', () => {
      this.convertInput.click();
    });
    
    // Handle file selection
    this.convertInput.addEventListener('change', async (e) => {
      const file = e.target.files[0];
      if (file) {
        await this._showConvertModal(file);
      }
      this.convertInput.value = '';
    });
    
    // Modal close button
    const closeBtn = document.getElementById('closeConvertModal');
    if (closeBtn) {
      closeBtn.addEventListener('click', () => this._hideConvertModal());
    }
    
    // Cancel button
    const cancelBtn = document.getElementById('cancelConvert');
    if (cancelBtn) {
      cancelBtn.addEventListener('click', () => this._hideConvertModal());
    }
    
    // Start convert button
    const startBtn = document.getElementById('startConvert');
    if (startBtn) {
      startBtn.addEventListener('click', () => this._executeConversion());
    }
    
    // Close on overlay click
    if (this.convertModal) {
      this.convertModal.addEventListener('click', (e) => {
        if (e.target === this.convertModal) {
          this._hideConvertModal();
        }
      });
    }
    
    // Update format description and options on change
    if (this.convertTargetFormat) {
      this.convertTargetFormat.addEventListener('change', () => {
        this._updateFormatDescription();
        this._updateConvertOptions();
      });
    }
    
    console.log('[Chat] File conversion ready');
  }
  
  /**
   * Update which advanced options are shown based on source and target format
   */
  _updateConvertOptions() {
    const targetFormat = this.convertTargetFormat?.value || '';
    const sourceType = this.pendingConvertFile?.file?.type || '';
    
    // Hide all option groups first
    const imageOpts = document.getElementById('convertImageOptions');
    const svgOpts = document.getElementById('convertSvgOptions');
    const videoOpts = document.getElementById('convertVideoOptions');
    const audioOpts = document.getElementById('convertAudioOptions');
    
    if (imageOpts) imageOpts.style.display = 'none';
    if (svgOpts) svgOpts.style.display = 'none';
    if (videoOpts) videoOpts.style.display = 'none';
    if (audioOpts) audioOpts.style.display = 'none';
    
    // Show relevant options based on target format
    const imageFormats = ['png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp', 'ico', 'tiff'];
    const videoFormats = ['mp4', 'webm', 'mov', 'avi', 'mkv'];
    const audioFormats = ['mp3', 'wav', 'flac', 'ogg', 'aac', 'm4a', 'extract_mp3', 'extract_wav'];
    
    if (targetFormat === 'svg') {
      // SVG has special potrace options
      if (svgOpts) svgOpts.style.display = 'block';
    } else if (imageFormats.includes(targetFormat)) {
      if (imageOpts) imageOpts.style.display = 'block';
    } else if (videoFormats.includes(targetFormat)) {
      if (videoOpts) videoOpts.style.display = 'block';
    } else if (audioFormats.includes(targetFormat)) {
      if (audioOpts) audioOpts.style.display = 'block';
    }
  }
  
  /**
   * Collect advanced options from the form
   */
  _collectConvertOptions() {
    const options = {};
    const targetFormat = this.convertTargetFormat?.value || '';
    
    // Image options
    const resize = document.getElementById('convertResize')?.value?.trim();
    const quality = document.getElementById('convertQuality')?.value;
    const stripMetadata = document.getElementById('convertStripMetadata')?.checked;
    const grayscale = document.getElementById('convertGrayscale')?.checked;
    
    if (resize) options.resize = resize;
    if (quality) options.quality = parseInt(quality);
    if (stripMetadata) options.strip_metadata = true;
    if (grayscale) options.grayscale = true;
    
    // SVG options
    const threshold = document.getElementById('convertThreshold')?.value?.trim();
    const turdsize = document.getElementById('convertTurdsize')?.value;
    
    if (threshold) options.threshold = threshold;
    if (turdsize) options.turdsize = parseInt(turdsize);
    
    // Video options
    const resolution = document.getElementById('convertResolution')?.value?.trim();
    const crf = document.getElementById('convertCrf')?.value;
    const fps = document.getElementById('convertFps')?.value;
    const duration = document.getElementById('convertDuration')?.value;
    
    if (resolution) options.resolution = resolution;
    if (crf) options.crf = parseInt(crf);
    if (fps) options.fps = parseInt(fps);
    if (duration) options.duration = parseInt(duration);
    
    // Audio options
    const bitrate = document.getElementById('convertBitrate')?.value;
    const sampleRate = document.getElementById('convertSampleRate')?.value;
    const channels = document.getElementById('convertChannels')?.value;
    
    if (bitrate) options.bitrate = bitrate;
    if (sampleRate) options.sample_rate = parseInt(sampleRate);
    if (channels) options.channels = parseInt(channels);
    
    return options;
  }
  
  /**
   * Reset advanced options form
   */
  _resetConvertOptions() {
    // Reset all input fields
    const inputs = ['convertResize', 'convertQuality', 'convertThreshold', 'convertTurdsize',
                    'convertResolution', 'convertCrf', 'convertFps', 'convertDuration'];
    inputs.forEach(id => {
      const el = document.getElementById(id);
      if (el) el.value = '';
    });
    
    // Reset checkboxes
    const checkboxes = ['convertStripMetadata', 'convertGrayscale'];
    checkboxes.forEach(id => {
      const el = document.getElementById(id);
      if (el) el.checked = false;
    });
    
    // Reset selects
    const selects = ['convertBitrate', 'convertSampleRate', 'convertChannels'];
    selects.forEach(id => {
      const el = document.getElementById(id);
      if (el) el.value = '';
    });
    
    // Close the details element
    const details = document.getElementById('convertAdvanced');
    if (details) details.removeAttribute('open');
  }

  _clearConvertPreview() {
    if (this.convertPreviewUrl) {
      URL.revokeObjectURL(this.convertPreviewUrl);
      this.convertPreviewUrl = null;
    }
    if (this.convertPreview) {
      this.convertPreview.innerHTML = '';
    }
  }
  
  /**
   * Show the conversion modal with file preview
   */
  async _showConvertModal(file) {
    if (!this.convertModal) return;
    
    // Validate file size (max 100MB for video)
    if (file.size > 100 * 1024 * 1024) {
      Utils.toast('File too large (max 100MB)', 'error');
      return;
    }
    
    // Store the file
    this.pendingConvertFile = { file, stashRef: null };
    
    // Update filename display
    const sizeKB = Math.round(file.size / 1024);
    const sizeStr = sizeKB > 1024 ? `${(sizeKB / 1024).toFixed(1)}MB` : `${sizeKB}KB`;
    this.convertFileName.textContent = `${file.name} (${sizeStr})`;
    
    // Show preview based on file type
    this._clearConvertPreview();
    if (file.type.startsWith('image/')) {
      const img = document.createElement('img');
      this.convertPreviewUrl = URL.createObjectURL(file);
      img.src = this.convertPreviewUrl;
      img.style.maxWidth = '200px';
      img.style.maxHeight = '150px';
      img.style.borderRadius = 'var(--radius-md)';
      this.convertPreview.appendChild(img);
      
      // Pre-select appropriate format based on current
      this._preselectFormat(file.name, 'image');
    } else if (file.type.startsWith('video/')) {
      const video = document.createElement('video');
      this.convertPreviewUrl = URL.createObjectURL(file);
      video.src = this.convertPreviewUrl;
      video.style.maxWidth = '200px';
      video.style.maxHeight = '150px';
      video.style.borderRadius = 'var(--radius-md)';
      video.controls = true;
      this.convertPreview.appendChild(video);
      
      this._preselectFormat(file.name, 'video');
    } else if (file.type.startsWith('audio/')) {
      const audio = document.createElement('audio');
      this.convertPreviewUrl = URL.createObjectURL(file);
      audio.src = this.convertPreviewUrl;
      audio.controls = true;
      this.convertPreview.appendChild(audio);
      
      this._preselectFormat(file.name, 'audio');
    } else {
      this.convertPreview.innerHTML = '<span style="font-size: 3rem;">📄</span>';
    }
    
    this._updateFormatDescription();
    this._updateConvertOptions();
    this._resetConvertOptions();
    this.convertModal.classList.add('active');
    window.jarvisApp?.backgroundTasks?.updateConvertHint();
    void window.jarvisApp?.backgroundTasks?.refresh();
  }
  
  /**
   * Pre-select target format based on source file type
   */
  _preselectFormat(filename, mediaType) {
    const ext = filename.split('.').pop().toLowerCase();
    
    if (mediaType === 'image') {
      // If it's a raster image, suggest PNG or WebP; if PNG, suggest WebP
      if (ext === 'png') {
        this.convertTargetFormat.value = 'webp';
      } else if (ext === 'jpg' || ext === 'jpeg') {
        this.convertTargetFormat.value = 'png';
      } else {
        this.convertTargetFormat.value = 'png';
      }
    } else if (mediaType === 'video') {
      // Suggest MP4 for compatibility
      this.convertTargetFormat.value = ext === 'mp4' ? 'webm' : 'mp4';
    } else if (mediaType === 'audio') {
      // Suggest MP3 for compatibility
      this.convertTargetFormat.value = ext === 'mp3' ? 'wav' : 'mp3';
    }
  }
  
  /**
   * Update the format description based on selection
   */
  _updateFormatDescription() {
    const format = this.convertTargetFormat.value;
    const descEl = document.getElementById('convertFormatDesc');
    if (!descEl) return;
    
    const descriptions = {
      'png': 'Lossless compression, supports transparency',
      'jpg': 'Good compression for photos, no transparency',
      'webp': 'Modern format, excellent compression + transparency',
      'gif': 'Supports animation, limited colors',
      'svg': 'Vector format - best for logos, icons, line art',
      'bmp': 'Uncompressed bitmap',
      'ico': 'Icon format for favicons',
      'mp4': 'Most compatible video format',
      'webm': 'Web-optimized video, smaller files',
      'mov': 'Apple QuickTime format',
      'avi': 'Legacy video format',
      'mp3': 'Universal audio format, good compression',
      'wav': 'Lossless audio, larger files',
      'flac': 'Lossless audio, good compression',
      'ogg': 'Open audio format',
      'aac': 'High-quality audio, Apple preferred',
      'extract_mp3': 'Extract audio track from video as MP3',
      'extract_wav': 'Extract audio track from video as WAV (lossless)'
    };
    
    descEl.textContent = descriptions[format] || 'Select a target format';
  }
  
  /**
   * Hide the conversion modal
   */
  _hideConvertModal() {
    if (this.convertModal) {
      this.convertModal.classList.remove('active');
    }
    this._clearConvertPreview();
    this.pendingConvertFile = null;
  }
  
  /**
   * Execute the file conversion
   */
  async _executeConversion() {
    if (!this.pendingConvertFile?.file) {
      Utils.toast('No file selected', 'error');
      return;
    }
    
    const file = this.pendingConvertFile.file;
    let targetFormat = this.convertTargetFormat.value;
    
    // Handle extract audio special cases
    const isExtract = targetFormat.startsWith('extract_');
    if (isExtract) {
      targetFormat = targetFormat.replace('extract_', '');
    }
    
    // Collect advanced options
    const options = this._collectConvertOptions();
    
    this._hideConvertModal();
    Utils.toast('Uploading file for conversion...', 'info', 2000);
    
    try {
      // Upload file to stash (bypasses vision analysis)
      const formData = new FormData();
      formData.append('file', file);
      formData.append('labels', 'for_conversion,uploaded');
      
      const uploadResponse = await fetch('/api/stash/upload', {
        method: 'POST',
        body: formData
      });
      
      if (!uploadResponse.ok) {
        throw new Error('Failed to upload file');
      }
      
      const uploadData = await uploadResponse.json();
      const stashRef = uploadData.stash_ref;
      
      // Build the conversion message
      let message;
      if (isExtract) {
        message = `Extract audio from the video at ${stashRef} and save as ${targetFormat.toUpperCase()}`;
      } else {
        message = `Convert the file at ${stashRef} to ${targetFormat.toUpperCase()} format`;
      }
      
      // Add options if any were specified
      if (Object.keys(options).length > 0) {
        const optionsList = Object.entries(options)
          .map(([k, v]) => `${k}=${v}`)
          .join(', ');
        message += ` with options: ${optionsList}`;
      }
      
      // Add hint to use convert_file tool
      message += `. Use the convert_file tool.`;
      
      // Send the message (no attached image = no vision analysis)
      this.inputField.value = message;
      await this.sendMessage({tool: 'convert_file', arguments: {
        source: stashRef, target_format: targetFormat, options
      }});
      
    } catch (err) {
      console.error('[Chat] Conversion error:', err);
      Utils.toast('Failed to start conversion: ' + err.message, 'error');
    }
  }
  
  /**
   * Route file attachment by type.
   */
  async attachFile(file) {
    if (file) await this._attachMultipleFiles([file]);
  }

  _isPdfFile(file) {
    if (!file) return false;
    const ext = String(file.name || '').split('.').pop().toLowerCase();
    const mime = String(file.type || '').toLowerCase();
    return ext === 'pdf' || mime === 'application/pdf' || mime === 'application/x-pdf';
  }

  _isAudioFile(file) {
    if (!file) return false;
    const ext = String(file.name || '').split('.').pop().toLowerCase();
    return ['aac', 'flac', 'm4a', 'mp3', 'mp4', 'mpeg', 'mpga', 'ogg', 'wav', 'webm'].includes(ext);
  }

  _isVideoFile(file) {
    if (!file) return false;
    const ext = String(file.name || '').split('.').pop().toLowerCase();
    const mime = String(file.type || '').split(';', 1)[0].trim().toLowerCase();
    // An audio/mpeg .mpeg can be an MP3 bitstream rather than a video
    // container. Preserve its established audio inspection/transcription path.
    if (ext === 'mpeg' && mime === 'audio/mpeg') return false;
    // Containers can contain audio alone. The server inspects their streams
    // and returns kind=audio when there are no video frames to analyze.
    return mime.startsWith('video/') || ['mp4', 'webm', 'mov', 'mkv', 'avi', 'm4v', 'mpeg', 'mpg'].includes(ext);
  }

  _createArtifactUploadId() {
    if (window.crypto?.randomUUID) {
      return window.crypto.randomUUID();
    }
    if (window.crypto?.getRandomValues) {
      const bytes = new Uint8Array(16);
      window.crypto.getRandomValues(bytes);
      bytes[6] = (bytes[6] & 0x0f) | 0x40;
      bytes[8] = (bytes[8] & 0x3f) | 0x80;
      const hex = Array.from(bytes, (value) => value.toString(16).padStart(2, '0')).join('');
      return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
    }
    // UUID shape is required for retry identity, not as an authentication
    // secret. This keeps older non-secure mobile WebViews functional.
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (char) => {
      const value = Math.floor(Math.random() * 16);
      return (char === 'x' ? value : ((value & 0x3) | 0x8)).toString(16);
    });
  }

  _renderDocumentPreviews() {
    if (!this.filePreviewContainer) return;
    for (const kind of ['audio', 'video']) {
      this.filePreviewContainer.querySelectorAll(kind).forEach(media => media.pause?.());
    }
    this.filePreviewContainer.replaceChildren();
    this.filePreviewContainer.style.display = this.attachedDocuments.length ? 'block' : 'none';
    this.attachedDocuments.forEach((item, index) => {
      const row = document.createElement('div');
      row.className = 'attachment-source';
      const info = document.createElement('div');
      info.className = 'file-preview';
      const label = document.createElement('span');
      label.className = 'file-name';
      label.textContent = `Source ${index + 1}: ${item.file.name}`;
      const size = document.createElement('span');
      size.className = 'file-size';
      size.textContent = `${(item.file.size / 1024).toFixed(1)} KB`;
      const remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'attachment-remove';
      remove.textContent = '×';
      remove.title = `Remove ${item.file.name}`;
      remove.setAttribute('aria-label', remove.title);
      remove.disabled = Boolean(this._attachmentSend);
      remove.addEventListener('click', () => this._removeAttachedDocument(item));
      info.append(label, size, remove);
      row.appendChild(info);
      const mediaKind = item.attachment?.kind || item.kind;
      if (['audio', 'video'].includes(mediaKind) && window.URL?.createObjectURL) {
        item.previewUrl ||= window.URL.createObjectURL(item.file);
        const media = document.createElement(mediaKind);
        media.controls = true;
        media.preload = 'metadata';
        media.className = `${mediaKind}-player file-${mediaKind}-player`;
        media.src = item.previewUrl;
        if (mediaKind === 'video') media.playsInline = true;
        row.appendChild(media);
      }
      this.filePreviewContainer.appendChild(row);
    });
  }

  _removeAttachedDocument(item) {
    if (this._attachmentSend) return;
    if (item.previewUrl) window.URL?.revokeObjectURL(item.previewUrl);
    this.attachedDocuments = this.attachedDocuments.filter(candidate => candidate !== item);
    this._renderDocumentPreviews();
  }

  clearAttachedFile() {
    if (this._attachmentSend) return false;
    this.attachedDocuments.forEach(item => {
      if (item.previewUrl) window.URL?.revokeObjectURL(item.previewUrl);
    });
    this.attachedDocuments = [];
    this._renderDocumentPreviews();
    return true;
  }

  async _uploadAttachedDocument(item, context) {
    if (item.attachment?.mode === context.mode) return item.attachment;
    const formData = new FormData();
    formData.append('file', item.file);
    formData.append('upload_id', item.uploadId);
    formData.append('mode', context.mode);
    const response = await fetch(`/api/upload-${item.kind}`, {
      method: 'POST', body: formData, signal: context.controller.signal
    });
    const payload = await response.json().catch(() => ({}));
    const returnedKind = payload.attachment?.kind;
    const compatibleKind = returnedKind === item.kind || (item.kind === 'video' && returnedKind === 'audio');
    if (!response.ok || !payload.ok || !payload.attachment?.stash_ref || !compatibleKind) {
      throw new Error(payload.error || `${item.file.name} could not be uploaded. Please retry.`);
    }
    // Cache even after cancellation if a late successful response arrives. A
    // retry uses the same committed artifact and never submits the stale turn.
    item.attachment = { ...payload.attachment, mode: context.mode };
    return item.attachment;
  }

  /**
   * Attach an image file (upload to server, then show action modal)
   */
  async attachImage(file) {
    await this.attachImageFiles([file]);
  }
  
  /**
   * Clear attached images
   */
  clearAttachedImage(options = {}) {
    if (this._attachmentSend) return;
    if (this._imageUpload) this.cancelAttachmentPreparation();
    this._clearPendingImageFiles();
    this.attachedImages = [];
    this.imageAttachmentAction = 'analyze';
    this.imageAttachmentSettings = {};
    if (!options.preserveVisionRetry) {
      this.pendingVisionRetryPayload = null;
    }
    this._renderImagePreviews();
  }

  /**
   * Upload the entire selected source bundle before sending one chat request.
   */
  async sendMessage(toolAction = null) {
    if (this._talkActive) return;
    if (this._voiceSession) return;
    if (this._conversationLoadPending) {
      Utils.toast('Wait for the conversation to finish loading.', 'info');
      return;
    }
    if (this.pendingImageFiles?.length) {
      Utils.toast('Retry or remove the pending images before sending.', 'info', 4000);
      return;
    }
    let rawMessage = this.inputField.value.trim();
    const hasImage = this._hasAttachedImages();
    const imagePayload = this._getImageAttachmentPayload();
    const documentStates = [...this.attachedDocuments];
    const hasPdf = documentStates.some(item => item.kind === 'pdf');
    const hasAudio = documentStates.some(item => item.kind === 'audio');
    const hasVideo = documentStates.some(item => item.kind === 'video');
    const hasFile = documentStates.length > 0;
    const hasSelectedToolHints = this.selectedToolHints.length > 0;
    
    // Need either message, image, or file
    if (!rawMessage && !hasImage && !hasFile && !hasSelectedToolHints) return;
    if (this.isProcessing) return;
    const attachmentError = this._validateAttachmentSelection([]);
    if (attachmentError) {
      Utils.toast(attachmentError, 'error', 4000);
      return;
    }
    if (hasImage && this.imageAttachmentAction !== 'analyze' && (hasFile || this.attachedImages.length !== 1)) {
      Utils.toast('Image editing and video generation require one reference image only.', 'error');
      return;
    }
    if (!window.jarvisSocket?.connected) {
      Utils.toast('Jarvis is not connected', 'error');
      return;
    }
    
    // Check for --feedback flag in message
    let requestFeedback = this.feedbackEnabled;
    if (rawMessage.includes('--feedback')) {
      requestFeedback = true;
      rawMessage = rawMessage.replace('--feedback', '').trim();
    }
    
    // Stop any currently playing audio (new message = new audio coming)
    if (window.jarvisApp && window.jarvisApp.stopAudioPlayback) {
      window.jarvisApp.stopAudioPlayback();
    }
    
    // Hide autocomplete
    this._hideAutocomplete();
    this._expirePendingCompletionGuardCards();
    
    // Parse workflows, prompts, and tool hints
    const parsed = window.commandSystem.parseInput(rawMessage);
    const requestedChatOnly = parsed.toolPolicy === 'none';
    const effectiveChatOnly = this.chatOnlyEnabled || requestedChatOnly;
    const toolHints = this._combineToolHints(parsed.toolHints || []);
    if (effectiveChatOnly && (parsed.workflow || toolHints.length > 0)) {
      Utils.toast('Turn off Chat only before using tools or workflows', 'info');
      return;
    }
    if (effectiveChatOnly && (hasImage || hasPdf || hasAudio || hasVideo)) {
      Utils.toast('Turn off Chat only before analyzing images, PDFs, audio, or video', 'info');
      return;
    }
    if (!parsed.message && requestedChatOnly && !hasImage && !hasFile) {
      this._setChatOnlyEnabled(true, { focus: false });
      this.inputField.value = '';
      Utils.autoResize(this.inputField);
      Utils.toast('Chat only is on until you remove the mode chip', 'success', 2200);
      return;
    }
    if (!parsed.message && toolHints.length > 0 && !hasImage && !hasFile) {
      Utils.toast('Add a task after the tool hint', 'info');
      return;
    }
    if (effectiveChatOnly && requestFeedback) {
      requestFeedback = false;
      Utils.toast('Feedback Analysis is unavailable in Chat only; sending without it', 'info', 2600);
    }
    if (requestedChatOnly) {
      this._setChatOnlyEnabled(true, { focus: false });
    }
    
    // Build display message (show original with decorations, show feedback badge if enabled)
    // The active badge already shows @prompt and recognized #tool selectors.
    // Keep the bubble focused on the user's task instead of displaying those
    // selectors twice. Workflows retain their original trigger text because
    // parseInput intentionally keeps it in parsed.message.
    const hasParsedSelectors = Boolean(parsed.prompt)
      || (parsed.toolHints || []).length > 0
      || parsed.toolPolicy === 'none';
    let displayMessage = hasParsedSelectors
      ? parsed.message
      : this.inputField.value.trim();
    let activeBadge = '';
    const displayParsed = {
      ...parsed,
      toolHints,
      toolPolicy: this.chatOnlyEnabled ? 'none' : null
    };
    if (displayParsed.workflow || displayParsed.prompt || toolHints.length > 0 || displayParsed.toolPolicy) {
      activeBadge = window.commandSystem.getActiveDisplay(displayParsed);
    }
    if (requestFeedback) {
      activeBadge += (activeBadge ? ' ' : '') + '<span class="badge badge-feedback">📊</span>';
    }
    
    // Upload sequentially so one failure never launches later uploads or a
    // partial chat. Successful references and retry UUIDs remain in the draft.
    const context = this._attachmentContext();
    const draftText = this.inputField.value;
    this._attachmentSend = context;
    this.isProcessing = true;
    this.updateSendButton();
    this._renderDocumentPreviews();
    const attachments = [];
    try {
      for (const item of documentStates) {
        if (!this._attachmentContextIsCurrent(context)) return;
        this.showThinking();
        this.showProgressStatus(`Preparing ${item.file.name}…`);
        attachments.push(await this._uploadAttachedDocument(item, context));
      }
      if (!this._attachmentContextIsCurrent(context)) return;
      if (this.inputField.value !== draftText) {
        Utils.toast('Your draft changed during upload. Review it and send when ready.', 'info', 4000);
        return;
      }
    } catch (err) {
      if (this._attachmentContextIsCurrent(context)) {
        Utils.toast(err.message || 'Attachment upload failed. Your draft is ready to retry.', 'error', 5000);
      }
      return;
    } finally {
      if (this._attachmentSend === context) {
        this._attachmentSend = null;
        this.hideThinking();
        this.clearStatus();
        this.isProcessing = false;
        this.updateSendButton();
        this._renderDocumentPreviews();
      }
    }
    if (!this._attachmentContextIsCurrent(context)) return;
    this.isProcessing = true;
    this.updateSendButton();

    this._resetPendingToolState();
    this.pendingVisionRetryPayload = ['analyze', 'image', 'video'].includes(imagePayload?.action)
      ? {
          action: imagePayload.action,
          settings: { ...(imagePayload.settings || {}) },
          images: imagePayload.images.map(({ url, filename }) => ({ url, filename }))
        }
      : null;
    
    // Pass parsed data to socket (workflows are handled by orchestrator via /trigger).
    const sent = window.jarvisSocket.sendMessage(parsed.message, imagePayload, {
      system_instruction: parsed.instruction,
      prompt_name: parsed.prompt,
      tool_hints: toolHints,
      tool_action: toolAction,
      tool_policy: effectiveChatOnly ? 'none' : 'auto'
    }, requestFeedback, null, attachments);
    if (!sent) {
      this.isProcessing = false;
      this.updateSendButton();
      Utils.toast('Jarvis disconnected before the message was sent. Retry when connected.', 'error');
      return;
    }

    this.currentMessageId = window.jarvisSocket.lastRequestId;
    this._pendingSend = {
      requestId: this.currentMessageId, text: draftText,
      documents: documentStates.map(item => ({ ...item, previewUrl: null })),
      images: [...this.attachedImages], toolHints: [...this.selectedToolHints],
      imageAction: this.imageAttachmentAction,
      imageSettings: { ...this.imageAttachmentSettings },
    };

    // Commit the local UI only after the upload and socket handoff both succeed.
    this._pendingSend.element = this.addUserMessage(
      displayMessage,
      imagePayload,
      activeBadge,
      attachments
    );
    this.rememberRenderedMessage('user', this.currentMessageId);
    this.inputField.value = '';
    this.selectedToolHints = [];
    this._renderToolHintChips();
    this._hideAmbientToolSuggestions();
    Utils.autoResize(this.inputField);
    
    // Clear attachments after sending
    this.clearAttachedImage({ preserveVisionRetry: true });
    this.clearAttachedFile();
  }

  /**
   * Submit one transcribed Talk turn through ordinary chat admission/history.
   */
  sendTalkMessage(text) {
    const socket = window.jarvisSocket;
    if (!this._talkActive || this.isProcessing || this._conversationLoadPending || !socket.connected) return null;
    this._resetPendingToolState();
    const sent = socket.sendMessage(text, null, {
      input_mode: 'talk', tool_hints: [...this.selectedToolHints],
      tool_policy: this.chatOnlyEnabled ? 'none' : 'auto'
    }, this.feedbackEnabled);
    if (!sent) return null;
    this.currentMessageId = socket.lastRequestId;
    this.isProcessing = true;
    this._pendingSend = {
      requestId: this.currentMessageId, text, documents: [], images: [],
      toolHints: [...this.selectedToolHints], imageAction: 'analyze', imageSettings: {},
      element: this.addUserMessage(text)
    };
    this.rememberRenderedMessage('user', this.currentMessageId);
    this.updateSendButton();
    return this.currentMessageId;
  }

  /** Add user message to chat with optional source attachments and badge. */
  addUserMessage(text, imageData = null, activeBadge = '', attachments = null) {
    const messageEl = document.createElement('div');
    messageEl.className = 'message user';
    
    const images = this._normalizeMessageImages(imageData);
    let imageHtml = '';
    if (images.length === 1) {
      imageHtml = `
        <div class="message-image" onclick="window.showImageLightbox('${images[0].url}')">
          <img src="${images[0].url}" alt="Image 1" loading="lazy">
          <div class="image-overlay">
            <span>🔍 Image 1 · Click to expand</span>
          </div>
        </div>`;
    } else if (images.length > 1) {
      imageHtml = `<div class="message-images">${images.map((img, index) => `
        <div class="message-image" onclick="window.showImageLightbox('${img.url}')">
          <img src="${img.url}" alt="Image ${index + 1}" loading="lazy">
          <div class="image-overlay">
            <span>🔍 Image ${index + 1}</span>
          </div>
        </div>`).join('')}</div>`;
    }
    
    let badgeHtml = '';
    if (activeBadge) {
      // Don't escape - activeBadge may contain valid HTML (like feedback badge)
      badgeHtml = `<div class="command-badge">${activeBadge}</div>`;
    }

    const sources = Array.isArray(attachments) ? attachments : [];
    const mediaHtml = sources.map(item => {
      if (item?.kind === 'video') return this._renderVideoAttachmentHtml(item);
      if (item?.kind === 'audio') {
        return this._renderAudioPlayerHtml(this._normalizeAudioAttachment(item), { cardClass: 'user-audio-attachment' });
      }
      return '';
    }).join('');
    const sourceHtml = sources.length
      ? `<ul class="message-source-list">${sources.map((item, index) => {
          const filename = Utils.escapeHtml(item.filename || 'Attached file');
          const label = `Source ${index + 1}: ${filename}`;
          const sourceUrl = ['pdf', 'text'].includes(item.kind)
            ? this._sourceAttachmentUrl(item)
            : null;
          if (!sourceUrl) return `<li>${label}</li>`;
          const url = Utils.escapeHtml(sourceUrl);
          return `<li><a href="${url}" target="_blank" rel="noopener noreferrer">${label}</a> <a href="${url}" download="${filename}" aria-label="Download ${filename}">Download</a></li>`;
        }).join('')}</ul>`
      : '';
    const defaultPromptText = sources.length + images.length > 1
      ? 'Review these attached sources.'
      : sources[0]?.kind === 'audio'
        ? 'Transcribe this audio recording.'
        : sources[0]?.kind === 'video'
          ? 'Analyze this video.'
          : sources[0]?.kind === 'pdf'
            ? "What's in this PDF?"
            : sources[0]?.kind === 'text'
              ? 'Summarize this file.'
              : "What's in this image?";
    const defaultPrompt = `<em>${defaultPromptText}</em>`;
    messageEl._jarvisMarkdownContent = text || defaultPromptText;

    messageEl.innerHTML = `
      <div class="message-bubble">
        ${badgeHtml}
        ${imageHtml}
        ${sourceHtml}
        ${text ? Utils.escapeHtml(text) : defaultPrompt}
      </div>
      ${mediaHtml}
    `;
    
    this.messagesContainer.appendChild(messageEl);
    Utils.scrollToBottom(this.messagesContainer);
    return messageEl;
  }

  /**
   * Skip assistant-side inline rendering for source uploads that were only analyzed.
   * Keep the stash metadata intact so follow-up turns can still re-use the image.
   */
  _shouldSkipAssistantInlineImage(item) {
    return Boolean(
      item
      && item.tool_origin === 'web_upload'
      && item.action === 'analyze'
    );
  }

  /**
   * Add assistant message to chat
   */
  addAssistantMessage(text, toolsUsed = [], data = {}, options = {}) {
    const objectIsContinuation = text?._kind === 'continuation' || text?._continuation_id;
    // Safety: ensure text is a string
    if (typeof text === 'object' && text !== null) {
      // Handle case where object was passed instead of string
      const obj = text;
      text = obj.text || obj.content || obj.speech || '';
      toolsUsed = obj.tools_used || obj.toolsUsed || toolsUsed || [];
      data = obj.data || data || {};
    }
    text = text || '';
    const late = options.late || objectIsContinuation || [data, data?.data].some(value =>
      value && (value._kind === 'continuation' || value._continuation_id));

    // Keep one consolidated action rail on only the latest Jarvis response.
    if (!late) this._clearMessageResponseActions();
    
    const messageEl = document.createElement('div');
    messageEl.className = 'message assistant new-message';
    const liveMessageId = data.message_id || data._web_message_id || data.data?._web_message_id || '';
    this.rememberRenderedMessage('assistant', liveMessageId);
    const conversationId = data.conversation_id || data.data?.conversation_id || window.jarvisSocket?.conversationId || '';
    if (liveMessageId) {
      messageEl.dataset.messageId = liveMessageId;
    }
    if (conversationId) {
      messageEl.dataset.conversationId = conversationId;
    }
    
    // Remove new-message class after animation completes (2.5s)
    setTimeout(() => {
      messageEl.classList.remove('new-message');
    }, 2500);

    if (late) {
      // Shared live/history boundary: late content cannot enter the legacy HTML
      // widgets, consume pending tools, or replace foreground response actions.
      window.continuationRenderer.append(messageEl, String(text), data.data || data);
      this.messagesContainer.appendChild(messageEl);
      window.jarvisApp?.backgroundTasks?.renderCards(messageEl, (data.data || data).background_jobs);
      Utils.scrollToBottom(this.messagesContainer);
      return;
    }
    
    // Build tool cards HTML from pendingTools (supports duplicate tools with unique keys)
    let toolResultsData = data.data || data || {};
    toolResultsData = this._flattenWorkflowToolResults(toolResultsData);
    let toolCardEntries = [];
    const toolTraceEntries = this._getToolTraceEntries(toolResultsData).filter(entry => entry.result_kind !== 'background_admission');
    if (!options.late) this._reconcilePendingToolsWithFinalList(toolsUsed, toolTraceEntries);
    const pendingToolEntries = options.late ? [] : Object.entries(this.pendingTools);
    if (pendingToolEntries.length > 0) {
      toolCardEntries = this._getPendingToolCardEntries(toolResultsData, pendingToolEntries);
    } else if (toolTraceEntries.length > 0) {
      const toolOccurrenceCounts = {};
      const successfulToolOccurrenceCounts = {};
      for (const entry of toolTraceEntries) {
        const tool = entry.tool;
        const occurrenceIndex = toolOccurrenceCounts[tool] || 0;
        toolOccurrenceCounts[tool] = occurrenceIndex + 1;
        const status = entry.skipped === true
          ? 'skipped'
          : entry.ok === false
            ? 'error'
            : 'success';
        const resultOccurrenceIndex = successfulToolOccurrenceCounts[tool] || 0;
        if (status === 'success') {
          successfulToolOccurrenceCounts[tool] = resultOccurrenceIndex + 1;
        }
        const fallback = status === 'error'
          ? this._getToolTraceFailureResult(entry)
          : status === 'skipped'
            ? this._getToolTraceSkippedResult(entry)
            : this._getToolTraceSuccessFallback(entry);
        const toolResult = status === 'success'
          ? this._getToolResultForOccurrence(
            toolResultsData,
            tool,
            resultOccurrenceIndex,
            fallback
          )
          : fallback;
        toolCardEntries.push({
          displayName: tool,
          status,
          result: toolResult,
          duration: entry.duration_ms ?? null
        });
      }
    } else if (toolsUsed.length > 0) {
      // Fallback for non-workflow responses
      const toolOccurrenceCounts = {};
      for (const tool of toolsUsed) {
        const occurrenceIndex = toolOccurrenceCounts[tool] || 0;
        toolOccurrenceCounts[tool] = occurrenceIndex + 1;
        const toolResult = this._getToolResultForOccurrence(toolResultsData, tool, occurrenceIndex);
        toolCardEntries.push({displayName: tool, status: 'success', result: toolResult, duration: null});
      }
    }
    const toolCardsHtml = window.assistantMessageRenderer.renderToolCards(
      toolCardEntries,
      entry => this._createToolCardHtml(entry.displayName, entry.status, entry.result, entry.duration)
    );

    // Check for generated images
    let imageHtml = '';
    let filename = null;
    
    // Method 1: Check data.generate_image object
    const imageData = data.generate_image;
    if (imageData && typeof imageData === 'object') {
      // Try various paths
      filename = imageData.file_path?.split('/').pop()
        || imageData.saved?.filename
        || imageData.saved?.path?.split('/').pop()
        || imageData.data?.file_path?.split('/').pop()
        || imageData.data?.saved?.filename;
      
      // Try JSON search
      if (!filename) {
        const jsonStr = JSON.stringify(imageData);
        const match = jsonStr.match(/generated_[^"]+\.(jpg|png|jpeg)/i);
        if (match) filename = match[0];
      }
    }
    
    // Method 2: Extract from speech/text (fallback)
    // Check both toolsUsed array and pendingTools (which may have step-keyed entries like generate_image_step5)
    const hasImageTool = toolsUsed.includes('generate_image') || 
      (!options.late && Object.keys(this.pendingTools).some(k => k.startsWith('generate_image')));
    if (!filename && hasImageTool) {
      const textToSearch = text + ' ' + JSON.stringify(data);
      const match = textToSearch.match(/generated_[\w\-]+\.(jpg|png|jpeg)/i);
      if (match) filename = match[0];
    }
    
    if (filename) {
      imageHtml = `
        <div class="message-image" onclick="window.showImageLightbox('/api/images/${filename}')">
          <img src="/api/images/${filename}" alt="Generated image" loading="lazy">
          <div class="image-overlay">
            <span>🔍 Click to expand</span>
          </div>
        </div>
      `;
    }
    
    // Method 3: Generic stash_ref image (qr_code_generator, screenshot_url, any tool saving images to stash)
    // Skip tools that have their own display blocks (convert_file, generate_image)
    const toolsWithOwnImageDisplay = ['convert_file', 'generate_image'];
    if (!imageHtml) {
      const imageExtensions = /\.(png|jpg|jpeg|gif|webp|bmp|ico|tiff?|svg)$/i;
      for (const [toolName, toolResult] of Object.entries(toolResultsData)) {
        if (toolsWithOwnImageDisplay.includes(toolName)) continue;
        // OCR filenames describe the input image; its stash refs point to
        // Markdown, JSON or archive outputs, including in saved conversations.
        if (toolName === 'document_ocr') continue;
        if (!toolResult || typeof toolResult !== 'object') continue;
        if (this._shouldSkipAssistantInlineImage(toolResult)) continue;
        const ref = toolResult.stash_ref || toolResult.ref;
        if (!ref) continue;
        const fn = toolResult.filename || toolResult.name || '';
        const mime = (toolResult.mime_type || '').trim().toLowerCase();
        const isImage = mime ? mime.startsWith('image/') : imageExtensions.test(fn);
        if (!isImage) continue;
        const stashMatch = ref.match(/stash:\/\/([^/]+)\/(.+)/);
        if (stashMatch) {
          const stashUrl = `/api/stash/${stashMatch[1]}/${stashMatch[2]}`;
          imageHtml = `
            <div class="message-image" onclick="window.showImageLightbox('${stashUrl}')">
              <img src="${stashUrl}" alt="Image from stash" loading="lazy">
              <div class="image-overlay">
                <span>🔍 Click to expand</span>
              </div>
            </div>
          `;
          break;
        }
      }
    }
    
    // Check for generated music
    let audioHtml = '';
    let audioUrl = null;
    let audioTitle = 'Generated Music';
    let audioFilename = 'generated-audio.mp3';
    let audioMimeType = 'audio/mpeg';
    let audioDuration = '';
    let genericStashAudio = false;
    
    // Method 1: Check data.generate_music object
    const musicData = data.generate_music;
    if (musicData && typeof musicData === 'object') {
      // Try various paths for audio URL
      audioUrl = musicData.audio_url
        || musicData.data?.audio_url
        || musicData.file_url;
      
      // If we have a stash reference, convert to API URL
      if (!audioUrl) {
        audioUrl = Utils.stashRefToApiUrl(
          musicData.stash_ref || musicData.data?.stash_ref
        );
      }
      
      // Or get the filename from file_path
      if (!audioUrl && musicData.file_path) {
        const musicFilename = musicData.file_path.split('/').pop();
        audioUrl = `/api/music/${encodeURIComponent(musicFilename)}`;
      }
      
      // Get title
      audioTitle = musicData.title || musicData.data?.title || 'Generated Music';
      audioFilename = musicData.filename
        || musicData.data?.filename
        || (musicData.file_path ? musicData.file_path.split('/').pop() : audioFilename);
      audioMimeType = this._inferAudioMimeType(
        audioUrl,
        audioFilename,
        musicData.mime_type || musicData.data?.mime_type
      );
      audioDuration = musicData.duration_seconds
        || musicData.duration
        || musicData.data?.duration_seconds
        || musicData.data?.duration
        || '';
    }
    
    // Method 2: Search in tool results data
    const hasMusicTool = toolsUsed.includes('generate_music') || 
      (!options.late && Object.keys(this.pendingTools).some(k => k.startsWith('generate_music')));
    if (!audioUrl && hasMusicTool) {
      const musicResult = toolResultsData['generate_music'];
      if (musicResult) {
        audioUrl = musicResult.audio_url 
          || musicResult.data?.audio_url
          || musicResult.file_url;
        
        if (!audioUrl) {
          audioUrl = Utils.stashRefToApiUrl(
            musicResult.stash_ref || musicResult.data?.stash_ref
          );
        }
        
        if (!audioUrl && musicResult.file_path) {
          const musicFilename = musicResult.file_path.split('/').pop();
          audioUrl = `/api/music/${encodeURIComponent(musicFilename)}`;
        }
        
        audioTitle = musicResult.title || musicResult.data?.title || audioTitle;
        audioFilename = musicResult.filename
          || musicResult.data?.filename
          || (musicResult.file_path ? musicResult.file_path.split('/').pop() : audioFilename);
        audioMimeType = this._inferAudioMimeType(
          audioUrl,
          audioFilename,
          musicResult.mime_type || musicResult.data?.mime_type
        );
        audioDuration = musicResult.duration_seconds
          || musicResult.duration
          || musicResult.data?.duration_seconds
          || musicResult.data?.duration
          || '';
      }
    }

    // Generic Stash audio: downloaded public recordings and audio artifacts
    // from any tool get a player without hardcoding each tool name.
    if (!audioUrl) {
      const genericAudio = this._findAudioFromToolResults(
        toolResultsData,
        ['convert_file', 'analyze_video']
      );
      if (genericAudio) {
        audioUrl = genericAudio.audioUrl;
        audioTitle = genericAudio.audioTitle;
        audioFilename = genericAudio.audioFilename;
        audioMimeType = genericAudio.audioMimeType;
        audioDuration = genericAudio.audioDuration;
        genericStashAudio = true;
      }
    }

    if (audioUrl) {
      audioHtml = this._renderAudioPlayerHtml({
        audioUrl,
        audioTitle,
        audioFilename,
        audioMimeType,
        audioDuration,
      });
    }
    
    // Check for generated video
    let videoHtml = '';
    let videoUrl = null;
    let videoTitle = 'Generated Video';
    let videoDuration = '';
    let videoHasAudio = false;
    let videoProvider = '';
    let videoMimeType = 'video/mp4';
    
    // Method 1: Check data.generate_video object
    const videoData = data.generate_video;
    if (videoData && typeof videoData === 'object') {
      // Try various paths for video URL - prefer local file over remote URL
      const savedInfo = videoData.saved || videoData.data?.saved;
      if (savedInfo?.filename) {
        videoUrl = `/api/videos/${savedInfo.filename}`;
        videoMimeType = this._inferVideoMimeType(savedInfo.filename, savedInfo.filename);
      }
      
      // Fallback to stash reference
      if (!videoUrl && videoData.stash_ref) {
        const stashMatch = videoData.stash_ref.match(/stash:\/\/([^/]+)\/(.+)/);
        if (stashMatch) {
          videoUrl = `/api/stash/${stashMatch[1]}/${stashMatch[2]}`;
          videoMimeType = this._inferVideoMimeType(videoUrl, videoData.filename, videoData.mime_type);
        }
      }
      
      // Fallback to file_path
      if (!videoUrl && videoData.file_path) {
        const videoFilename = videoData.file_path.split('/').pop();
        videoUrl = `/api/videos/${videoFilename}`;
        videoMimeType = this._inferVideoMimeType(videoFilename, videoFilename);
      }
      
      // Last resort: remote URL (may expire)
      if (!videoUrl && videoData.video_url) {
        videoUrl = videoData.video_url;
        videoMimeType = this._inferVideoMimeType(videoData.video_url, videoData.filename, videoData.mime_type);
      }
      
      // Get duration, title, audio, and provider
      videoDuration = videoData.duration || videoData.data?.duration || '';
      videoHasAudio = videoData.has_audio || videoData.data?.has_audio || false;
      videoProvider = videoData.provider || videoData.data?.provider || '';
      videoTitle = videoData.prompt 
        ? `Generated Video: ${videoData.prompt.substring(0, 50)}${videoData.prompt.length > 50 ? '...' : ''}`
        : 'Generated Video';
    }
    
    // Method 1.5: Generic video from any tool (youtube_video, create_social_clip, etc.)
    // Modular: detects video by filename/mime/stash_ref — not by tool name
    if (!videoUrl) {
      const genericVideo = this._findVideoFromToolResults(toolResultsData, ['convert_file', 'analyze_video']);
      if (genericVideo) {
        videoUrl = genericVideo.videoUrl;
        videoTitle = genericVideo.videoTitle;
        videoDuration = genericVideo.videoDuration;
        videoHasAudio = genericVideo.videoHasAudio;
        videoProvider = genericVideo.videoProvider;
        videoMimeType = genericVideo.videoMimeType;
      }
    }

    // Method 2: Search in tool results data
    const hasVideoTool = toolsUsed.includes('generate_video') ||
      (!options.late && Object.keys(this.pendingTools).some(k => k.startsWith('generate_video')));
    if (!videoUrl && hasVideoTool) {
      const videoResult = toolResultsData['generate_video'];
      if (videoResult) {
        const savedInfo = videoResult.saved || videoResult.data?.saved;
        if (savedInfo?.filename) {
          videoUrl = `/api/videos/${savedInfo.filename}`;
          videoMimeType = this._inferVideoMimeType(savedInfo.filename, savedInfo.filename);
        }
        
        if (!videoUrl && videoResult.stash_ref) {
          const stashMatch = videoResult.stash_ref.match(/stash:\/\/([^/]+)\/(.+)/);
          if (stashMatch) {
            videoUrl = `/api/stash/${stashMatch[1]}/${stashMatch[2]}`;
            videoMimeType = this._inferVideoMimeType(videoUrl, videoResult.filename, videoResult.mime_type);
          }
        }
        
        if (!videoUrl && videoResult.file_path) {
          const videoFilename = videoResult.file_path.split('/').pop();
          videoUrl = `/api/videos/${videoFilename}`;
          videoMimeType = this._inferVideoMimeType(videoFilename, videoFilename);
        }
        
        if (!videoUrl && videoResult.video_url) {
          videoUrl = videoResult.video_url;
          videoMimeType = this._inferVideoMimeType(videoResult.video_url, videoResult.filename, videoResult.mime_type);
        }
        
        videoDuration = videoResult.duration || videoResult.data?.duration || videoDuration;
        videoHasAudio = videoResult.has_audio || videoResult.data?.has_audio || videoHasAudio;
        videoProvider = videoResult.provider || videoResult.data?.provider || videoProvider;
        if (videoResult.prompt) {
          videoTitle = `Generated Video: ${videoResult.prompt.substring(0, 50)}${videoResult.prompt.length > 50 ? '...' : ''}`;
        }
      }
    }
    
    if (videoUrl) {
      const durationStr = videoDuration ? `${videoDuration}s` : '';
      const audioStr = videoHasAudio ? ' 🔊' : '';
      const providerStr = videoProvider ? ` (${videoProvider})` : '';
      const videoPosterUrl = videoUrl.startsWith('/api/videos/')
        ? `${videoUrl}/thumbnail`
        : '';
      videoHtml = `
        <div class="message-video">
          <div class="video-header">
            <span class="video-icon">🎬</span>
            <span class="video-title">${Utils.escapeHtml(videoTitle)}</span>
          </div>
          <video controls preload="metadata" class="video-player"${videoPosterUrl ? ` poster="${videoPosterUrl}"` : ''}>
            <source src="${videoUrl}"${videoMimeType ? ` type="${videoMimeType}"` : ''}>
            Your browser does not support video playback.
          </video>
          ${(durationStr || audioStr) ? `<div class="video-info"><span class="video-duration">${durationStr}${audioStr}${providerStr}</span></div>` : ''}
        </div>
      `;
    }
    
    // Converted-file display is separate from the composer's conversion flow.
    const hasConvertTool = toolsUsed.includes('convert_file') ||
      (!options.late && Object.keys(this.pendingTools).some(k => k.startsWith('convert_file')));
    const convertedFileHtml = hasConvertTool
      ? window.assistantMessageRenderer.renderConvertedFile(toolResultsData['convert_file'] || data.convert_file)
      : '';

    // raw_llm_response is inside data.data (nested), also check top level for loaded conversations
    const innerData = data.data || data || {};
    let rawResponse = innerData.raw_llm_response || innerData.vision_analysis || data.raw_llm_response || data.vision_analysis || '';
    if (typeof rawResponse !== 'string') rawResponse = '';
    rawResponse = Utils.stripLlmCitationArtifacts(rawResponse);
    const storedSpeech = Utils.stripLlmCitationArtifacts(String(innerData.speech || data.speech || ''));
    text = Utils.stripLlmCitationArtifacts(text);

    const shoppingHtml = window.structuredResultsRenderer
      ? ''
      : window.assistantMessageRenderer.renderShoppingFallback(toolResultsData, data);

    const canvasPreview = this._extractCanvasPreview(toolResultsData, data);
    const canvasPreviewHtml = canvasPreview
      ? this._renderCanvasPreviewHtml(canvasPreview)
      : '';
    const structuredResultsHtml = window.structuredResultsRenderer
      ? window.structuredResultsRenderer.render(toolResultsData, data, toolsUsed)
      : '';

    let chartHtml = '';
    const cryptoChartResult = toolResultsData.crypto_chart;
    const cryptoChartData = cryptoChartResult?.data?.series?.prices
      ? cryptoChartResult.data
      : (cryptoChartResult?.series?.prices ? cryptoChartResult : null);

    if (cryptoChartData?.series?.prices?.length) {
      const chartConfig = {
        title: `${cryptoChartData.coin || 'Crypto'} ${cryptoChartData.range_label || 'chart'}`,
        coin: cryptoChartData.coin,
        coin_id: cryptoChartData.coin_id,
        vs_currency: cryptoChartData.vs_currency,
        days: cryptoChartData.days,
        range_label: cryptoChartData.range_label,
        current_price: cryptoChartData.current_price,
        change_percent: cryptoChartData.change_percent,
        points_returned: cryptoChartData.points_returned,
        series: cryptoChartData.series
      };
      chartHtml = `
        <div class="crypto-chart-embed" data-crypto-chart="${encodeURIComponent(JSON.stringify(chartConfig))}">
          <div class="crypto-chart-loading">Loading chart…</div>
        </div>
      `;
    }

    // Prefer the richer raw response for chat display when it is the same answer with
    // better visual structure. This keeps TTS concise while avoiding paragraph blobs.
    if (this._shouldPreferRawForDisplay(rawResponse, storedSpeech, text)) {
      text = rawResponse;
    }

    const youtubeEmbeds = this._collectYouTubeEmbeds(text, rawResponse, toolResultsData);
    const youtubeEmbedsHtml = youtubeEmbeds.map((embed) => `
      <div class="message-video youtube-embed">
        <div class="video-header">
          <span class="video-icon">▶</span>
          <span class="video-title">${Utils.escapeHtml(embed.title)}</span>
        </div>
        <div class="video-embed-shell">
          <iframe
            class="video-embed-frame"
            src="${embed.embedUrl}"
            title="${Utils.escapeHtml(embed.title)}"
            loading="lazy"
            referrerpolicy="strict-origin-when-cross-origin"
            allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
            allowfullscreen
          ></iframe>
        </div>
        <div class="video-info">
          <a href="${embed.watchUrl}" target="_blank" rel="noopener noreferrer" class="content-link">Open on YouTube</a>
        </div>
      </div>
    `).join('');

    const parsedText = Utils.parseMarkdown(text);
    
    // Build expandable details section
    let detailsHtml = '';
    const hasDetails = rawResponse && rawResponse !== text && rawResponse.length > text.length;
    
    if (hasDetails) {
      const detailsContent = Utils.escapeHtmlAndLinkify(rawResponse);
      detailsHtml = `
        <div class="message-details collapsed">
          <button class="details-toggle" title="Show full LLM response">
            <span class="toggle-icon">▶</span>
            <span class="toggle-text">Show details</span>
          </button>
          <div class="details-content">
            <pre>${detailsContent}</pre>
          </div>
        </div>
      `;
    }
    
    const messageBubbleHtml = `
      <div class="message-bubble">
        ${chartHtml}
        ${parsedText}
        ${detailsHtml}
      </div>
    `;

    messageEl.innerHTML = `
      ${toolCardsHtml}
      ${structuredResultsHtml}
      ${shoppingHtml}
      ${imageHtml}
      ${convertedFileHtml}
      ${genericStashAudio ? '' : audioHtml}
      ${videoHtml}
      ${youtubeEmbedsHtml}
      ${canvasPreviewHtml}
      ${messageBubbleHtml}
      ${genericStashAudio ? audioHtml : ''}
    `;
    
    // Add click handler for details toggle
    const detailsToggle = messageEl.querySelector('.details-toggle');
    if (detailsToggle) {
      detailsToggle.addEventListener('click', (e) => {
        e.stopPropagation();
        const details = detailsToggle.closest('.message-details');
        details.classList.toggle('collapsed');
        const icon = detailsToggle.querySelector('.toggle-icon');
        const text = detailsToggle.querySelector('.toggle-text');
        const isCollapsed = details.classList.contains('collapsed');
        icon.textContent = isCollapsed ? '▶' : '▼';
        text.textContent = isCollapsed ? 'Show details' : 'Hide details';
      });
    }
    
    // Add click handlers for tool cards
    messageEl.querySelectorAll('.tool-card-header').forEach(header => {
      header.addEventListener('click', () => {
        header.parentElement.classList.toggle('expanded');
      });
    });

    messageEl.querySelectorAll('.message-image.converted-file[data-converted-image-url]').forEach(image => {
      image.addEventListener('click', () => {
        window.showImageLightbox(image.dataset.convertedImageUrl);
      });
    });

    if (!options.late && !toolResultsData.pending_jobs) this._attachCompletionGuardCard(messageEl, data, toolsUsed);
    this._attachMessageResponseActions(messageEl, text, data, {
      allowReaction: options.allowReaction !== false,
      allowCanvas: !toolsUsed.includes('canvas')
    });
    
    this.messagesContainer.appendChild(messageEl);
    window.jarvisApp?.backgroundTasks?.renderCards(messageEl, toolResultsData.background_jobs);
    Utils.hydrateRichContent(messageEl);
    if (canvasPreview) {
      this._hydrateCanvasPreview(messageEl, canvasPreview);
    }
    Utils.scrollToBottom(this.messagesContainer);
    
    // Clear only this response's pending tool state. Late events from another
    // message remain isolated instead of contaminating the next response.
    if (!options.late) this._clearPendingToolsForMessage(liveMessageId);
  }

  _activatePendingToolsForMessage(messageId, reset = false) {
    const normalizedId = String(messageId || '').trim();
    if (!normalizedId) return this.pendingTools;

    if (reset || !this.pendingToolsByMessage.has(normalizedId)) {
      this.pendingToolsByMessage.set(normalizedId, {});
    }
    this.pendingToolMessageId = normalizedId;
    this.pendingTools = this.pendingToolsByMessage.get(normalizedId);
    return this.pendingTools;
  }

  _reconcilePendingToolsWithFinalList(toolsUsed = [], toolTraceEntries = []) {
    const traceEntries = Array.isArray(toolTraceEntries)
      ? toolTraceEntries.filter(entry => entry?.tool)
      : [];
    if ((!Array.isArray(toolsUsed) || toolsUsed.length === 0) && traceEntries.length === 0) return;

    const existingEntries = Object.entries(this.pendingTools);
    const entriesByTool = new Map();
    for (const entry of existingEntries) {
      const toolName = entry[1]?.toolName || entry[0].replace(/_(?:step|final)\d+(?:_\d+)?$/, '');
      if (!entriesByTool.has(toolName)) entriesByTool.set(toolName, []);
      entriesByTool.get(toolName).push(entry);
    }

    const reconciled = {};
    const usedCardIds = new Set();
    const orderedEntries = traceEntries.length > 0
      ? traceEntries.map(entry => ({
        toolName: entry.tool,
        status: entry.skipped === true
          ? 'skipped'
          : entry.ok === false
            ? 'error'
            : 'success',
        result: entry.skipped === true
          ? this._getToolTraceSkippedResult(entry)
          : entry.ok === false
            ? this._getToolTraceFailureResult(entry)
            : this._getToolTraceSuccessFallback(entry),
        args: entry.arguments || {},
        duration: entry.duration_ms ?? null,
        workflowStep: entry.workflow_step ?? null
      }))
      : toolsUsed.map(toolName => ({
        toolName,
        status: 'success',
        result: null,
        args: {},
        duration: null
      }));

    orderedEntries.forEach((entry, index) => {
      const toolName = entry.toolName;
      const toolQueue = entriesByTool.get(toolName) || [];
      const workflowCardId = entry.workflowStep != null
        ? `${toolName}_step${entry.workflowStep}`
        : null;
      const workflowCardIndex = workflowCardId
        ? toolQueue.findIndex(([cardId]) => cardId === workflowCardId)
        : -1;
      const queued = workflowCardIndex >= 0
        ? toolQueue.splice(workflowCardIndex, 1)[0]
        : toolQueue.shift();
      let cardId = queued?.[0] || `${toolName}_final${index}`;
      while (usedCardIds.has(cardId)) cardId = `${cardId}_${index}`;
      usedCardIds.add(cardId);
      const toolData = queued?.[1] || {
        toolName,
        status: entry.status,
        args: entry.args,
        result: entry.result,
        duration: entry.duration
      };
      toolData.status = entry.status || toolData.status || 'success';
      if (
        entry.status === 'skipped'
        || toolData.result === null
        || toolData.result === undefined
      ) {
        toolData.result = entry.result;
      }
      if (toolData.duration === null || toolData.duration === undefined) toolData.duration = entry.duration;
      reconciled[cardId] = toolData;
    });

    for (const [cardId, toolData] of existingEntries) {
      if (!usedCardIds.has(cardId)) reconciled[cardId] = toolData;
    }

    this.pendingTools = reconciled;
    if (this.pendingToolMessageId) {
      this.pendingToolsByMessage.set(this.pendingToolMessageId, reconciled);
    }
  }

  _clearPendingToolsForMessage(messageId) {
    const normalizedId = String(messageId || this.pendingToolMessageId || '').trim();
    if (normalizedId) this.pendingToolsByMessage.delete(normalizedId);
    if (!normalizedId || this.pendingToolMessageId === normalizedId) {
      this.pendingToolMessageId = null;
      this.pendingTools = {};
    }
  }

  _resetPendingToolState() {
    this.pendingToolsByMessage.clear();
    this.pendingToolMessageId = null;
    this.pendingTools = {};
  }

  sendResponseToCanvas(responseText, button = null) {
    if (this.chatOnlyEnabled) {
      Utils.toast('Turn off Chat only before sending a response to Canvas', 'info');
      return;
    }
    if (this.isProcessing) {
      Utils.toast('Wait for the current response to finish first', 'info');
      return;
    }
    if (!window.jarvisSocket?.connected) {
      Utils.toast('Jarvis is not connected', 'error');
      return;
    }

    const excerpt = this._buildCanvasExportExcerpt(responseText);
    const prompt = [
      'Create a new Canvas page from the selected Jarvis response and its relevant supporting results in this conversation.',
      'Use exactly one canvas call with action=create. Include all useful source links from the prior turn.',
      'Treat structured prior tool results as authoritative content; the selected response preview below may be truncated.',
      'Preserve useful source links and any image, video, audio, or stash references so Canvas can render the original media.',
      'Use a descriptive title and organize the result as readable Markdown.',
      excerpt ? `Selected response preview: "${excerpt}"` : ''
    ].filter(Boolean).join(' ');

    if (window.jarvisApp?.stopAudioPlayback) {
      window.jarvisApp.stopAudioPlayback();
    }
    this._expirePendingCompletionGuardCards();
    this.addUserMessage(prompt, null, '<span class="badge">📄 Canvas</span>');
    this.isProcessing = true;
    this._resetPendingToolState();
    this.updateSendButton();

    if (button) {
      button.disabled = true;
      setTimeout(() => {
        button.disabled = false;
      }, 1000);
    }

    window.jarvisSocket.sendMessage(
      prompt,
      null,
      { tool_hints: ['canvas'], request_kind: 'canvas_export', tool_rag_limit: 3 },
      false,
      null
    );
  }

  _flattenWorkflowToolResults(toolResultsData = {}) {
    const workflowResults = Array.isArray(toolResultsData?.results)
      ? toolResultsData.results
      : [];
    if (!workflowResults.length) return toolResultsData;

    const flat = {};
    for (const step of workflowResults) {
      if (step?.skipped === true) continue;
      const tool = step.tool || 'unknown';
      const rawOutputs = Array.isArray(step.outputs) ? step.outputs : [];
      const stepOutputs = rawOutputs.length
        ? rawOutputs.map(output => output?.data ?? output ?? {})
        : [step.data ?? {}];

      for (const stepOutput of stepOutputs) {
        if (flat[tool] === undefined) {
          flat[tool] = stepOutput;
        } else if (Array.isArray(flat[tool])) {
          flat[tool].push(stepOutput);
        } else {
          flat[tool] = [flat[tool], stepOutput];
        }
      }
    }
    return { ...toolResultsData, ...flat };
  }

  _extractCanvasPreview(toolResultsData = {}, data = {}) {
    const rawCanvas = toolResultsData?.canvas ?? data?.canvas;
    const candidates = Array.isArray(rawCanvas) ? [...rawCanvas].reverse() : [rawCanvas];

    const trace = data?._tool_trace || data?.data?._tool_trace;
    if (Array.isArray(trace)) {
      for (const entry of [...trace].reverse()) {
        if (entry?.tool !== 'canvas' || entry?.ok === false) continue;
        const args = entry.arguments;
        if (!args || typeof args !== 'object' || !args.page_id) continue;
        candidates.push({
          page_id: args.page_id,
          title: args.title || 'Canvas Page'
        });
      }
    }

    for (const candidate of candidates) {
      if (!candidate || typeof candidate !== 'object') continue;
      const payload = candidate.data && typeof candidate.data === 'object'
        ? candidate.data
        : candidate;
      const pageId = payload.page_id || payload.id || payload.canvas_page_id;
      if (!pageId) continue;

      const title = String(payload.title || 'Canvas Page').trim() || 'Canvas Page';
      const configuredBase = String(payload.base_url || '').trim().replace(/\/$/, '');
      let pageUrl = String(payload.url || '').trim();
      if (!pageUrl && configuredBase) {
        pageUrl = `${configuredBase}/${encodeURIComponent(pageId)}`;
      }
      if (!pageUrl) {
        pageUrl = `http://${window.location.hostname}:8890/${encodeURIComponent(pageId)}`;
      }

      try {
        let parsed = new URL(pageUrl);
        if (!['http:', 'https:'].includes(parsed.protocol)) continue;
        const origin = window.JarvisUINavigation?.url('canvas', parsed.origin) || parsed.origin;
        if (origin !== parsed.origin) {
          parsed = new URL(`${origin}${parsed.pathname}${parsed.search}${parsed.hash}`);
        }
        return {
          pageId: String(pageId),
          title,
          url: parsed.href,
          apiUrl: `${parsed.origin}/api/pages/${encodeURIComponent(pageId)}`,
          tags: Array.isArray(payload.tags) ? payload.tags : []
        };
      } catch (error) {
        continue;
      }
    }

    return null;
  }

  _renderCanvasPreviewHtml(preview) {
    const pageUrl = Utils.safeHttpUrlForAttr(preview.url);
    if (!pageUrl) return '';

    return `
      <div class="canvas-inline-preview" data-canvas-preview="${Utils.escapeHtml(preview.pageId)}">
        <a class="canvas-preview-thumbnail" href="${pageUrl}" target="_blank" rel="noopener noreferrer" aria-label="Open Canvas page: ${Utils.escapeHtml(preview.title)}">
          <div class="canvas-preview-sheet">
            <div class="canvas-preview-kicker">
              <span class="canvas-preview-icon">📄</span>
              <span>Jarvis Canvas</span>
            </div>
            <div class="canvas-preview-image" hidden>
              <img alt="" loading="lazy">
            </div>
            <div class="canvas-preview-copy">
              <div class="canvas-preview-title">${Utils.escapeHtml(preview.title)}</div>
              <div class="canvas-preview-excerpt" data-canvas-preview-excerpt>
                <span></span><span></span><span></span><span></span>
              </div>
            </div>
            <div class="canvas-preview-page-id">${Utils.escapeHtml(preview.pageId)}</div>
          </div>
        </a>
        <a class="canvas-preview-open-link" href="${pageUrl}" target="_blank" rel="noopener noreferrer">
          Open in Canvas <span aria-hidden="true">↗</span>
        </a>
      </div>
    `;
  }

  _canvasPreviewImageUrl(content, preview) {
    const match = String(content || '').match(/!\[[^\]]*\]\(([^)\s]+)\)/);
    if (!match) return '';
    const raw = match[1].trim();

    const stashMatch = raw.match(/^stash:\/\/([^/\s?#]+)\/([^/\s?#]+)/);
    if (stashMatch) {
      try {
        const origin = new URL(preview.url).origin;
        return `${origin}/api/stash/${encodeURIComponent(stashMatch[1])}/${encodeURIComponent(stashMatch[2])}`;
      } catch (error) {
        return '';
      }
    }

    try {
      const resolved = new URL(raw, preview.url);
      return ['http:', 'https:'].includes(resolved.protocol) ? resolved.href : '';
    } catch (error) {
      return '';
    }
  }

  _canvasPreviewExcerpt(content) {
    return String(content || '')
      .replace(/!\[[^\]]*\]\([^)]+\)/g, ' ')
      .replace(/```[\s\S]*?```/g, ' ')
      .replace(/https?:\/\/\S+/g, ' ')
      .replace(/(^|\n)\s*#{1,6}\s*/g, ' ')
      .replace(/[*_`>~\[\]]/g, '')
      .replace(/\s+/g, ' ')
      .trim()
      .slice(0, 220);
  }

  async _hydrateCanvasPreview(messageEl, preview) {
    const container = messageEl.querySelector('.canvas-inline-preview');
    if (!container) return;

    try {
      const response = await fetch(preview.apiUrl);
      if (!response.ok) return;
      const page = await response.json();
      if (!container.isConnected) return;

      const titleEl = container.querySelector('.canvas-preview-title');
      if (titleEl && page.title) titleEl.textContent = page.title;

      const excerpt = this._canvasPreviewExcerpt(page.content || '');
      const excerptEl = container.querySelector('[data-canvas-preview-excerpt]');
      if (excerptEl && excerpt) {
        excerptEl.textContent = excerpt;
        excerptEl.classList.add('has-content');
      }

      const imageUrl = this._canvasPreviewImageUrl(page.content || '', preview);
      const imageWrap = container.querySelector('.canvas-preview-image');
      const image = imageWrap?.querySelector('img');
      if (imageWrap && image && imageUrl) {
        image.src = imageUrl;
        image.alt = page.title ? `${page.title} preview` : 'Canvas page preview';
        imageWrap.hidden = false;
        container.classList.add('has-image');
      }
    } catch (error) {
      console.warn('Could not hydrate Canvas preview:', error);
    }
  }

  _normalizeDisplayText(text) {
    if (!text) return '';
    return String(text)
      .replace(/[*_`#>]+/g, '')
      .replace(/\s+/g, ' ')
      .trim();
  }

  _buildCanvasExportExcerpt(text, maxChars = 800) {
    const normalized = this._normalizeDisplayText(text);
    if (normalized.length <= maxChars) return normalized;

    let excerpt = normalized.slice(0, maxChars).trimEnd();
    if (normalized.charAt(maxChars) !== ' ') {
      const boundary = excerpt.lastIndexOf(' ');
      excerpt = boundary > 0 ? excerpt.slice(0, boundary).trimEnd() : '';
    }

    return `${excerpt}... [truncated]`;
  }

  _safeMediaUrlForAttr(raw) {
    const value = String(raw || '').trim();
    if (!value) return '';
    if (value.startsWith('/') && !value.startsWith('//')) {
      return Utils.escapeHtml(value);
    }
    return Utils.safeHttpUrlForAttr(value);
  }

  _inferAudioMimeType(urlOrPath = '', filename = '', declaredMime = '') {
    const normalizedMime = String(declaredMime || '').split(';', 1)[0].trim().toLowerCase();
    if (normalizedMime.startsWith('audio/')) return normalizedMime;

    const candidate = String(filename || urlOrPath || '').toLowerCase().split(/[?#]/, 1)[0];
    if (candidate.endsWith('.wav')) return 'audio/wav';
    if (candidate.endsWith('.flac')) return 'audio/flac';
    if (candidate.endsWith('.ogg')) return 'audio/ogg';
    if (candidate.endsWith('.opus')) return 'audio/opus';
    if (candidate.endsWith('.aac')) return 'audio/aac';
    if (candidate.endsWith('.webm')) return 'audio/webm';
    if (candidate.endsWith('.m4a') || candidate.endsWith('.mp4')) return 'audio/mp4';
    return 'audio/mpeg';
  }

  _isAudioMedia(filename = '', mimeType = '', directUrl = '') {
    const audioExtensions = /\.(aac|flac|m4a|mp3|mpeg|mpga|ogg|opus|wav)(\?|$|#)/i;
    if (String(mimeType || '').toLowerCase().startsWith('audio/')) return true;
    if (audioExtensions.test(String(filename))) return true;
    return Boolean(directUrl && audioExtensions.test(String(directUrl)));
  }

  _formatAudioDuration(value) {
    const seconds = Number(value);
    if (!Number.isFinite(seconds) || seconds <= 0) return '';
    const rounded = Math.round(seconds);
    const minutes = Math.floor(rounded / 60);
    const remainder = String(rounded % 60).padStart(2, '0');
    return minutes > 0 ? `${minutes}:${remainder}` : `${rounded}s`;
  }

  _sourceAttachmentUrl(attachment) {
    const url = Utils.stashRefToApiUrl(attachment?.stash_ref);
    if (!url) return null;
    const mode = ['cloud', 'local'].includes(attachment.mode)
      ? attachment.mode
      : globalThis.window?.jarvisSocket?.mode;
    return ['cloud', 'local'].includes(mode) ? `${url}?mode=${mode}` : url;
  }

  _normalizeAudioAttachment(attachment) {
    if (!attachment || typeof attachment !== 'object' || attachment.kind !== 'audio') {
      return null;
    }
    const audioUrl = this._sourceAttachmentUrl(attachment);
    if (!audioUrl) return null;

    const filename = String(attachment.filename || attachment.name || 'Audio recording');
    return {
      audioUrl,
      audioTitle: filename,
      audioFilename: filename,
      audioMimeType: this._inferAudioMimeType(
        audioUrl,
        filename,
        attachment.mime_type
      ),
      audioDuration: attachment.duration_seconds || attachment.duration || '',
    };
  }

  _renderVideoAttachmentHtml(attachment) {
    const sourceUrl = this._sourceAttachmentUrl(attachment);
    if (!sourceUrl) return '';
    const videoUrl = this._safeMediaUrlForAttr(sourceUrl);
    if (!videoUrl) return '';
    const filename = String(attachment.filename || 'Video');
    const title = Utils.escapeHtml(filename);
    const mimeType = this._inferVideoMimeType(sourceUrl, filename, attachment.mime_type);
    const duration = this._formatAudioDuration(attachment.duration_seconds || attachment.duration);
    const audioLabel = attachment.has_audio === false ? 'No audio track'
      : attachment.has_audio === true ? 'Includes audio' : '';
    const details = [duration, audioLabel].filter(Boolean).join(' · ');
    return `
      <div class="message-video user-video-attachment">
        <div class="video-header">
          <span class="video-icon">🎬</span>
          <span class="video-title">${title}</span>
        </div>
        <video controls playsinline preload="metadata" class="video-player" aria-label="${title}">
          <source src="${videoUrl}"${mimeType ? ` type="${Utils.escapeHtml(mimeType)}"` : ''}>
          Your browser does not support this video format. Open or download the original below.
        </video>
        <div class="video-info">
          <span>${Utils.escapeHtml(details)}</span>
          <span class="video-actions">
            <a href="${videoUrl}" target="_blank" rel="noopener noreferrer">Open original</a>
            <a href="${videoUrl}" download="${title}">Download</a>
          </span>
        </div>
      </div>
    `;
  }

  _formatVideoTimestamp(value) {
    if (value === null || value === undefined || value === '') return '';
    const seconds = Math.round(Number(value) * 100) / 100;
    if (!Number.isFinite(seconds) || seconds < 0) return '';
    const minutes = Math.floor(seconds / 60);
    const remainder = (seconds % 60).toFixed(2).replace(/\.?0+$/, '');
    return `${minutes}:${remainder.split('.')[0].padStart(2, '0')}${remainder.includes('.') ? `.${remainder.split('.')[1]}` : ''}`;
  }

  _renderVideoAnalysisResult(result) {
    if (!result || typeof result !== 'object' || Array.isArray(result)) return null;
    const data = result.data && typeof result.data === 'object' ? result.data : result;
    if (!data.visual_status && !data.audio_status && !data.analysis && !Array.isArray(data.frame_timestamps)) return null;
    const excerpt = (value, limit) => {
      const text = String(value || '');
      return Utils.escapeHtml(text.length > limit ? `${text.slice(0, limit)}… [excerpt truncated]` : text);
    };
    const visualLabels = {complete:'Sampled frames analyzed', partial:'Some frames analyzed', unavailable:'Visual analysis unavailable'};
    const audioLabels = {no_audio:'No audio track', skipped:'Audio not requested', transcribed:'Transcribed', no_speech:'No speech detected', partial:'Partial transcript', unavailable:'Audio transcription unavailable'};
    const start = this._formatVideoTimestamp(data.start_seconds);
    const end = this._formatVideoTimestamp(data.end_seconds);
    const timestamps = (Array.isArray(data.frame_timestamps) ? data.frame_timestamps : [])
      .slice(0, 6).map(value => this._formatVideoTimestamp(value)).filter(Boolean);
    const analyzedTimestamps = Array.isArray(data.analyzed_frame_timestamps)
      ? data.analyzed_frame_timestamps.slice(0, 6).map(value => this._formatVideoTimestamp(value)).filter(Boolean)
      : null;
    const incompleteFrameAnalysis = analyzedTimestamps !== null
      && (analyzedTimestamps.length !== timestamps.length
          || analyzedTimestamps.some((value, index) => value !== timestamps[index]));
    const warnings = (Array.isArray(data.warnings) ? data.warnings : []).slice(0, 8);
    const error = data.error || result.error;
    const source = {
      kind:'video', stash_ref:data.source_stash_ref || data.source_ref,
      filename:data.source_filename || data.filename || 'Video source',
      duration_seconds:data.duration_seconds, mime_type:data.mime_type,
      has_audio:data.has_audio ?? (data.audio_status === 'no_audio' ? false : undefined),
      mode:data.mode || result.mode
    };
    return `
      ${data.partial ? '<p class="video-analysis-warning"><strong>Partial analysis</strong></p>' : ''}
      ${start && end ? `<p><strong>Requested interval:</strong> ${start}–${end}</p>` : ''}
      <p><strong>Frames sampled:</strong> ${timestamps.length ? timestamps.join(', ') : 'None'}. Samples do not cover every frame.</p>
      ${incompleteFrameAnalysis ? `<p><strong>Frames analyzed:</strong> ${analyzedTimestamps.length ? analyzedTimestamps.join(', ') : 'None'}.</p>` : ''}
      <p><strong>Visuals:</strong> ${Utils.escapeHtml(visualLabels[data.visual_status] || 'Status not reported')}<br>
        <strong>Audio:</strong> ${Utils.escapeHtml(audioLabels[data.audio_status] || 'Status not reported')}</p>
      ${warnings.length ? `<ul class="video-analysis-warning">${warnings.map(warning => `<li>${excerpt(warning, 500)}</li>`).join('')}</ul>` : ''}
      ${error ? `<p class="video-analysis-warning">${excerpt(error, 1000)}</p>` : ''}
      ${data.analysis ? `<p><strong>Analysis</strong></p><div class="video-analysis-text">${excerpt(data.analysis, 10000)}</div>` : ''}
      ${data.transcript ? `<details class="video-analysis-transcript"><summary>Transcript</summary><div class="video-analysis-text">${excerpt(data.transcript, 8000)}</div></details>` : ''}
      ${this._renderVideoAttachmentHtml(source)}
    `;
  }

  _renderAudioPlayerHtml(audio, options = {}) {
    if (!audio || typeof audio !== 'object') return '';
    const audioUrl = this._safeMediaUrlForAttr(audio.audioUrl);
    if (!audioUrl) return '';

    const title = String(audio.audioTitle || audio.audioFilename || 'Audio');
    const filename = String(audio.audioFilename || 'audio');
    const mimeType = this._inferAudioMimeType(
      audio.audioUrl,
      filename,
      audio.audioMimeType
    );
    const duration = this._formatAudioDuration(audio.audioDuration);
    const cardClass = options.cardClass === 'user-audio-attachment'
      ? ' user-audio-attachment'
      : '';

    return `
      <div class="message-audio${cardClass}">
        <div class="audio-header">
          <span class="audio-icon">🎵</span>
          <span class="audio-title">${Utils.escapeHtml(title)}</span>
        </div>
        <audio controls preload="metadata" class="audio-player">
          <source src="${audioUrl}" type="${Utils.escapeHtml(mimeType)}">
          Your browser does not support audio playback.
        </audio>
        <div class="audio-info">
          ${duration ? `<span>${Utils.escapeHtml(duration)}</span>` : '<span></span>'}
          <span class="audio-actions">
            <a
              href="${audioUrl}"
              target="_blank"
              rel="noopener noreferrer"
              class="audio-open-link"
            >Open</a>
            <a
              href="${audioUrl}"
              download="${Utils.escapeHtml(filename)}"
              class="audio-download-link"
            >Download</a>
          </span>
        </div>
      </div>
    `;
  }

  /** Find the first generic Stash-backed audio artifact from any tool result. */
  _findAudioFromToolResults(toolResultsData, excludeTools = []) {
    if (!toolResultsData || typeof toolResultsData !== 'object') return null;

    for (const [toolName, toolResult] of Object.entries(toolResultsData)) {
      if (excludeTools.includes(toolName)) continue;

      const candidates = Array.isArray(toolResult) ? toolResult : [toolResult];
      for (const candidate of candidates) {
        const media = this._extractMediaFieldsFromToolResult(candidate);
        if (!media) continue;
        if (!this._isAudioMedia(media.filename, media.mimeType, media.directUrl)) continue;

        const audioUrl = Utils.stashRefToApiUrl(media.stashRef);
        if (!audioUrl) continue;
        const title = String(media.title || media.filename || 'Audio');

        return {
          audioUrl,
          audioTitle: title.length > 80 ? `${title.substring(0, 80)}...` : title,
          audioFilename: media.filename || 'audio',
          audioMimeType: this._inferAudioMimeType(
            audioUrl,
            media.filename,
            media.mimeType
          ),
          audioDuration: media.duration,
        };
      }
    }

    return null;
  }

  _inferVideoMimeType(urlOrPath = '', filename = '', declaredMime = '') {
    if (declaredMime && String(declaredMime).toLowerCase().startsWith('video/')) {
      return String(declaredMime).toLowerCase();
    }

    const candidate = String(filename || urlOrPath || '').toLowerCase();
    if (candidate.endsWith('.webm')) return 'video/webm';
    if (candidate.endsWith('.mov')) return 'video/quicktime';
    if (candidate.endsWith('.avi')) return 'video/x-msvideo';
    if (candidate.endsWith('.mkv')) return 'video/x-matroska';
    if (candidate.endsWith('.m4v')) return 'video/mp4';
    return 'video/mp4';
  }

  /** Pull stash/media fields from tool results (supports nested saved objects). */
  _extractMediaFieldsFromToolResult(toolResult) {
    if (!toolResult || typeof toolResult !== 'object') return null;

    const saved = toolResult.saved || toolResult.data?.saved || {};
    const nested = toolResult.data && typeof toolResult.data === 'object'
      ? toolResult.data
      : {};
    const filePath = toolResult.file_path
      || nested.file_path
      || saved.path
      || saved.file_path
      || '';
    const filename = toolResult.filename
      || toolResult.name
      || nested.filename
      || nested.name
      || saved.filename
      || (filePath ? String(filePath).split('/').pop() : '');

    return {
      stashRef: toolResult.stash_ref
        || toolResult.ref
        || nested.stash_ref
        || nested.ref
        || saved.stash_ref
        || saved.ref
        || null,
      filename,
      mimeType: String(
        toolResult.mime_type || nested.mime_type || saved.mime_type || ''
      ).toLowerCase(),
      directUrl: toolResult.audio_url
        || toolResult.video_url
        || toolResult.file_url
        || nested.audio_url
        || nested.video_url
        || nested.file_url
        || toolResult.url
        || nested.url
        || null,
      title: toolResult.video_title
        || toolResult.title
        || toolResult.prompt
        || toolResult.subject
        || nested.video_title
        || nested.title
        || nested.prompt
        || nested.subject
        || null,
      duration: toolResult.duration_seconds
        || toolResult.duration
        || nested.duration_seconds
        || nested.duration
        || '',
      hasAudio: toolResult.has_audio || nested.has_audio || false,
      provider: toolResult.provider || nested.provider || '',
    };
  }

  _isVideoMedia(filename = '', mimeType = '', directUrl = '') {
    const videoExtensions = /\.(mp4|webm|mov|avi|mkv|m4v)(\?|$|#)/i;
    if (mimeType.startsWith('video/')) return true;
    if (videoExtensions.test(String(filename))) return true;
    if (directUrl && videoExtensions.test(String(directUrl))) return true;
    return false;
  }

  /** Modular video lookup: any tool with stash/video fields, no hardcoded tool names. */
  _findVideoFromToolResults(toolResultsData, excludeTools = []) {
    if (!toolResultsData || typeof toolResultsData !== 'object') return null;

    for (const [toolName, toolResult] of Object.entries(toolResultsData)) {
      if (excludeTools.includes(toolName)) continue;

      const candidates = Array.isArray(toolResult) ? toolResult : [toolResult];
      for (const candidate of candidates) {
        const media = this._extractMediaFieldsFromToolResult(candidate);
        if (!media) continue;
        if (!this._isVideoMedia(media.filename, media.mimeType, media.directUrl)) continue;

        let videoUrl = null;
        if (media.stashRef) {
          const stashMatch = media.stashRef.match(/stash:\/\/([^/]+)\/(.+)/);
          if (stashMatch) {
            videoUrl = `/api/stash/${stashMatch[1]}/${stashMatch[2]}`;
          }
        }
        if (!videoUrl && media.directUrl) {
          videoUrl = media.directUrl;
        }
        if (!videoUrl && media.filename && media.filename.includes('.')) {
          videoUrl = `/api/videos/${media.filename}`;
        }
        if (!videoUrl) continue;

        const titlePrefix = media.title
          ? `${media.title.substring(0, 50)}${media.title.length > 50 ? '...' : ''}`
          : (media.filename ? `Video: ${media.filename}` : 'Video');

        return {
          videoUrl,
          videoTitle: media.title ? titlePrefix : (media.filename ? `Video: ${media.filename}` : 'Video'),
          videoDuration: media.duration,
          videoHasAudio: media.hasAudio,
          videoProvider: media.provider,
          videoMimeType: this._inferVideoMimeType(videoUrl, media.filename, media.mimeType),
        };
      }
    }

    return null;
  }

  _extractYouTubeVideoId(url) {
    if (!url) return null;

    try {
      const parsed = new URL(url, window.location.origin);
      const host = parsed.hostname.toLowerCase().replace(/^www\./, '');

      if (host === 'youtu.be') {
        const id = parsed.pathname.split('/').filter(Boolean)[0];
        return id || null;
      }

      if (!host.endsWith('youtube.com') && host !== 'youtube-nocookie.com') {
        return null;
      }

      const pathParts = parsed.pathname.split('/').filter(Boolean);
      if (parsed.pathname === '/watch') {
        return parsed.searchParams.get('v');
      }
      if (pathParts[0] === 'embed' || pathParts[0] === 'shorts' || pathParts[0] === 'live') {
        return pathParts[1] || null;
      }
    } catch (error) {
      return null;
    }

    return null;
  }

  /** Pull SerpApi YouTube payloads with tool provenance for iframe embedding. */
  _youtubeToolPayloadsForEmbeds(toolResultsData = {}) {
    const out = [];
    if (!toolResultsData || typeof toolResultsData !== 'object') return out;
    for (const key of ['serpapi_youtube_search', 'serpapi_youtube']) {
      const tr = toolResultsData[key];
      if (!tr) continue;
      if (Array.isArray(tr)) {
        for (const item of tr) {
          if (item && typeof item === 'object') {
            const payload = item.data && typeof item.data === 'object' ? item.data : item;
            out.push({toolName: key, payload});
          }
        }
      } else if (typeof tr === 'object') {
        const payload = tr.data && typeof tr.data === 'object' ? tr.data : tr;
        out.push({toolName: key, payload});
      }
    }
    return out;
  }

  _collectYouTubeEmbeds(displayText, rawResponse, toolResultsData = {}) {
    const maxEmbeds = 5;
    const urlRegex = /https?:\/\/[^\s<>"')\]]+/gi;
    const downloadedIds = new Set();

    for (const toolResult of Object.values(toolResultsData || {})) {
      if (!toolResult || typeof toolResult !== 'object') continue;
      if (!toolResult.stash_ref) continue;

      const sourceUrl = toolResult.url || toolResult.youtube_url || '';
      const videoId = this._extractYouTubeVideoId(sourceUrl);
      if (videoId) {
        downloadedIds.add(videoId);
      }
    }

    const embeds = [];
    const seenIds = new Set();
    const youtubeSearchResultIds = new Set();

    const pushEmbed = (videoId, titleHint = '') => {
      if (!videoId || seenIds.has(videoId) || downloadedIds.has(videoId)) return;
      if (embeds.length >= maxEmbeds) return;
      seenIds.add(videoId);
      const t = typeof titleHint === 'string' ? titleHint.trim() : '';
      embeds.push({
        videoId,
        title: t,
        watchUrl: `https://www.youtube.com/watch?v=${videoId}`,
        embedUrl: `https://www.youtube-nocookie.com/embed/${videoId}`,
      });
    };

    for (const {toolName, payload} of this._youtubeToolPayloadsForEmbeds(toolResultsData)) {
      const primaryTitle = typeof payload.title === 'string' ? payload.title.trim() : '';
      const candidates = new Map();
      const addCandidate = (videoId, titleHint = '') => {
        if (!videoId) return;
        const id = String(videoId).trim();
        if (!id) return;
        const title = typeof titleHint === 'string' ? titleHint.trim() : '';
        if (!candidates.has(id) || (!candidates.get(id) && title)) candidates.set(id, title);
      };
      if (payload.top_url) {
        const vid = this._extractYouTubeVideoId(payload.top_url);
        if (vid) addCandidate(vid, primaryTitle);
      }
      if (typeof payload.url === 'string') {
        const vid = this._extractYouTubeVideoId(payload.url);
        if (vid) addCandidate(vid, primaryTitle);
      }
      if (payload.video_id != null && String(payload.video_id).trim()) {
        addCandidate(String(payload.video_id).trim(), primaryTitle);
      }
      for (const listKey of ['results', 'top_results', 'candidates']) {
        const list = payload[listKey];
        if (!Array.isArray(list)) continue;
        for (const item of list) {
          if (!item || typeof item !== 'object') continue;
          const itemTitle = typeof item.title === 'string' ? item.title.trim() : '';
          const hint = itemTitle || primaryTitle;
          if (typeof item.url === 'string') {
            const vid = this._extractYouTubeVideoId(item.url);
            if (vid) addCandidate(vid, hint);
          } else if (item.video_id != null && String(item.video_id).trim()) {
            addCandidate(String(item.video_id).trim(), hint);
          }
        }
      }
      if (toolName === 'serpapi_youtube_search') {
        for (const videoId of candidates.keys()) youtubeSearchResultIds.add(videoId);
        const first = candidates.entries().next().value;
        if (first) pushEmbed(first[0], first[1]);
      } else {
        for (const [videoId, title] of candidates.entries()) pushEmbed(videoId, title);
      }
    }

    const sources = [displayText, rawResponse];

    for (const source of sources) {
      if (!source || embeds.length >= maxEmbeds) continue;

      const matches = String(source).match(urlRegex) || [];
      for (const rawUrl of matches) {
        if (embeds.length >= maxEmbeds) break;

        const videoId = this._extractYouTubeVideoId(rawUrl);
        if (
          !videoId
          || seenIds.has(videoId)
          || downloadedIds.has(videoId)
          || youtubeSearchResultIds.has(videoId)
        ) continue;

        pushEmbed(videoId, '');
      }
    }

    return embeds.map((embed, index) => ({
      ...embed,
      title: embed.title && embed.title.trim()
        ? embed.title.trim()
        : (embeds.length === 1 ? 'YouTube Video' : `YouTube Video ${index + 1}`),
    }));
  }

  _shouldPreferRawForDisplay(rawResponse, storedSpeech = '', fallbackText = '') {
    if (!rawResponse) return false;

    const effectiveSpeech = (storedSpeech || fallbackText || '').trim();
    if (!effectiveSpeech) return true;

    const rawHasStructure = rawResponse.includes('\n') || /(^|\n)\s*[-*]\s+/.test(rawResponse);
    const speechHasStructure = effectiveSpeech.includes('\n') || /(^|\n)\s*[-*]\s+/.test(effectiveSpeech);
    if (rawHasStructure && !speechHasStructure) return true;
    if (!rawHasStructure || speechHasStructure) return false;

    const normalizedRaw = this._normalizeDisplayText(rawResponse);
    const normalizedSpeech = this._normalizeDisplayText(effectiveSpeech);
    if (!normalizedRaw || !normalizedSpeech) return false;

    let prefixLen = 0;
    while (
      prefixLen < normalizedRaw.length &&
      prefixLen < normalizedSpeech.length &&
      normalizedRaw[prefixLen] === normalizedSpeech[prefixLen]
    ) {
      prefixLen += 1;
    }
    if (prefixLen >= 40) return true;

    const speechHead = normalizedSpeech.slice(0, 120);
    const rawHead = normalizedRaw.slice(0, 120);
    if (speechHead && normalizedRaw.includes(speechHead)) return true;
    if (rawHead && normalizedSpeech.includes(rawHead)) return true;
    return false;
  }

  _markCompletionGuardCardInactive(card, status, reason = '') {
    if (!card) return;

    const statusEl = card.querySelector('.completion-guard-status');
    const timerEl = card.querySelector('.completion-guard-timer');
    const yesBtn = card.querySelector('.completion-guard-yes');
    const noBtn = card.querySelector('.completion-guard-no');
    const noteInput = card.querySelector('.completion-guard-note-input');
    const body = card.querySelector('.completion-guard-body');
    const isExpired = status === 'expired';
    const statusText = isExpired ? 'Expired' : 'Skipped';
    const summaryText = isExpired
      ? 'This manual check is no longer active because the session changed or the prompt timed out.'
      : 'This manual check was skipped because you continued the conversation.';

    card.classList.remove('submitting');
    card.classList.add('expired');
    card.dataset.guardStatus = status;
    if (reason) card.dataset.guardReason = reason;
    if (statusEl) statusEl.textContent = statusText;
    if (timerEl) timerEl.remove();
    if (yesBtn) yesBtn.disabled = true;
    if (noBtn) noBtn.disabled = true;
    if (noteInput) noteInput.disabled = true;
    if (body) {
      body.innerHTML = `<div class="completion-guard-summary">${Utils.escapeHtml(summaryText)}</div>`;
    }
  }

  _expirePendingCompletionGuardCards() {
    const cards = this.messagesContainer.querySelectorAll('.completion-guard-card');
    cards.forEach((card) => {
      if (card.classList.contains('resolved') || card.classList.contains('submitting') || card.classList.contains('expired')) {
        return;
      }
      if (!card.querySelector('.completion-guard-yes') && !card.querySelector('.completion-guard-no')) {
        return;
      }
      this._markCompletionGuardCardInactive(card, 'superseded', 'conversation_continued');
    });
  }

  _formatCompletionGuardRemaining(ms) {
    const totalSeconds = Math.max(0, Math.ceil(ms / 1000));
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = totalSeconds % 60;
    return `${minutes}:${String(seconds).padStart(2, '0')}`;
  }

  _startCompletionGuardCountdown(card, expiresInMs) {
    if (!card || expiresInMs <= 0) return;

    const statusEl = card.querySelector('.completion-guard-status');
    if (!statusEl) return;

    let timerEl = card.querySelector('.completion-guard-timer');
    if (!timerEl) {
      timerEl = document.createElement('span');
      timerEl.className = 'completion-guard-timer';
      statusEl.insertAdjacentElement('afterend', timerEl);
    }

    const expiresAt = Date.now() + expiresInMs;
    card.dataset.expiresAt = String(expiresAt);
    const updateTimer = () => {
      if (!card.isConnected) return false;
      if (card.classList.contains('resolved') || card.classList.contains('submitting') || card.classList.contains('expired')) {
        return false;
      }

      const remaining = expiresAt - Date.now();
      if (remaining <= 0) {
        this._markCompletionGuardCardInactive(card, 'expired', 'manual_prompt_timeout');
        return false;
      }

      timerEl.textContent = `${this._formatCompletionGuardRemaining(remaining)} left`;
      return true;
    };

    updateTimer();
    const intervalId = window.setInterval(() => {
      if (!updateTimer()) {
        window.clearInterval(intervalId);
      }
    }, 1000);
  }

  _getCompletionGuardState(data, toolsUsed = []) {
    const innerData = data.data || data || {};
    const persisted = innerData._completion_guard || data._completion_guard || null;
    const live = data.completion_guard || innerData.completion_guard || null;
    const messageId = data.message_id || innerData._web_message_id || '';
    const conversationId = data.conversation_id || innerData.conversation_id || window.jarvisSocket?.conversationId || '';

    return {
      live,
      persisted,
      messageId,
      conversationId,
      toolsUsed
    };
  }

  _attachCompletionGuardCard(messageEl, data, toolsUsed = []) {
    const state = this._getCompletionGuardState(data, toolsUsed);
    const shouldPrompt = state.live?.prompt_user === true;
    const persistedStatus = state.persisted?.status || '';
    const hasPersistedState = Boolean(persistedStatus)
      && !['repair_response', 'auto_accepted'].includes(persistedStatus);

    if (!shouldPrompt && !hasPersistedState) {
      return;
    }

    const card = document.createElement('div');
    card.className = 'completion-guard-card';
    card.dataset.messageId = state.messageId || messageEl.dataset.messageId || '';
    card.dataset.conversationId = state.conversationId || messageEl.dataset.conversationId || '';

    if (hasPersistedState && !shouldPrompt) {
      const note = state.persisted.note || '';
      const ticketPath = state.persisted.ticket_path || '';
      let statusText = 'Completed correctly?';
      let summaryText = '';
      let extraClass = '';

      if (persistedStatus === 'ticket_created') {
        statusText = 'Ticket created';
        summaryText = 'This response was marked incomplete and logged for follow-up.';
        extraClass = ' resolved';
      } else if (persistedStatus === 'accepted') {
        statusText = 'Accepted';
        summaryText = 'Marked as completed correctly.';
        extraClass = ' resolved';
      } else if (persistedStatus === 'repaired') {
        statusText = 'Repaired';
        summaryText = 'A repair pass found a better answer and added it below.';
        extraClass = ' resolved';
      } else if (persistedStatus === 'tighten_only') {
        statusText = 'Tightened only';
        summaryText = 'Completion Guard reviewed this response, but did not find a material evidence or tool-path change worth surfacing as a repair.';
        extraClass = ' resolved';
      } else if (persistedStatus === 'repairing') {
        statusText = 'Repairing...';
        summaryText = 'Trying one follow-up pass using the existing task context.';
        extraClass = ' submitting';
      } else if (persistedStatus === 'cancelled') {
        statusText = 'Cancelled';
        summaryText = 'Repair was stopped before it finished. You can leave it as-is or try again.';
      } else if (persistedStatus === 'interrupted') {
        statusText = 'Interrupted';
        summaryText = 'The Web server restarted during this repair. It was not retried.';
      } else if (persistedStatus === 'unresolved') {
        statusText = 'Unresolved';
        summaryText = ticketPath
          ? 'One repair pass could not fully resolve this, so it was logged for follow-up.'
          : 'One repair pass could not fully resolve this response.';
      } else if (persistedStatus === 'noted') {
        statusText = 'Noted';
        summaryText = 'Saved your completion note.';
        extraClass = ' resolved';
      } else if (persistedStatus === 'expired') {
        statusText = 'Expired';
        summaryText = 'This manual check is no longer active because the session changed or the prompt timed out.';
        extraClass = ' expired';
      } else if (persistedStatus === 'superseded') {
        statusText = 'Skipped';
        summaryText = 'This manual check was skipped because you continued the conversation.';
        extraClass = ' expired';
      }

      card.className += extraClass;
      card.innerHTML = `
        <div class="completion-guard-header">
          <span class="completion-guard-title">🛡️ Completion Guard</span>
          <span class="completion-guard-status">${Utils.escapeHtml(statusText)}</span>
        </div>
        <div class="completion-guard-body">
          <div class="completion-guard-summary">${Utils.escapeHtml(summaryText)}</div>
          ${note ? `<div class="completion-guard-note">Note: ${Utils.escapeHtml(note)}</div>` : ''}
          ${ticketPath ? `<div class="completion-guard-ticket">Ticket: <code>${Utils.escapeHtml(ticketPath)}</code></div>` : ''}
        </div>
      `;
      messageEl.appendChild(card);
      return;
    }

    card.innerHTML = `
      <div class="completion-guard-header">
        <span class="completion-guard-title">🛡️ Completion Guard</span>
        <span class="completion-guard-status">Completed correctly?</span>
      </div>
      <div class="completion-guard-body">
        <input
          type="text"
          class="completion-guard-note-input"
          placeholder="Optional note if something was wrong or missing"
        >
        <div class="completion-guard-actions">
          <button type="button" class="completion-guard-btn completion-guard-yes">Yes</button>
          <button type="button" class="completion-guard-btn completion-guard-no">No</button>
        </div>
        <div class="completion-guard-summary">Marking "No" runs one repair attempt before logging a follow-up ticket.</div>
      </div>
    `;

    const yesBtn = card.querySelector('.completion-guard-yes');
    const noBtn = card.querySelector('.completion-guard-no');
    const noteInput = card.querySelector('.completion-guard-note-input');
    const statusEl = card.querySelector('.completion-guard-status');
    const summaryEl = card.querySelector('.completion-guard-summary');
    const expiresInMs = Number(state.live?.expires_in_ms || 0);

    yesBtn?.addEventListener('click', () => {
      yesBtn.disabled = true;
      if (noBtn) noBtn.disabled = true;
      if (noteInput) noteInput.disabled = true;

      window.jarvisSocket.emit('completion_guard:submit', {
        message_id: card.dataset.messageId,
        conversation_id: card.dataset.conversationId || window.jarvisSocket?.conversationId || '',
        accepted: true,
        note: noteInput?.value || ''
      });
    });

    noBtn?.addEventListener('click', () => {
      const messageId = card.dataset.messageId;
      if (!messageId) {
        Utils.toast('Missing message id for Completion Guard', 'error');
        return;
      }

      this._clearMessageResponseActions();
      card.classList.add('submitting');
      statusEl.textContent = 'Repairing...';
      summaryEl.textContent = 'Trying one follow-up pass before logging a ticket.';
      yesBtn.disabled = true;
      noBtn.disabled = true;
      if (noteInput) noteInput.disabled = true;

      window.jarvisSocket.emit('completion_guard:submit', {
        message_id: messageId,
        conversation_id: card.dataset.conversationId || window.jarvisSocket?.conversationId || '',
        accepted: false,
        note: noteInput?.value || ''
      });
    });

    messageEl.appendChild(card);

    this._startCompletionGuardCountdown(card, expiresInMs);
  }

  _ensureCompletionGuardCard(messageId, conversationId = '') {
    if (!messageId) return null;

    let card = this.messagesContainer.querySelector(`.completion-guard-card[data-message-id="${messageId}"]`);
    if (card) return card;

    const messageEl = this.messagesContainer.querySelector(`.message.assistant[data-message-id="${messageId}"]`);
    if (!messageEl) return null;

    card = document.createElement('div');
    card.className = 'completion-guard-card';
    card.dataset.messageId = messageId;
    card.dataset.conversationId = conversationId || messageEl.dataset.conversationId || window.jarvisSocket?.conversationId || '';
    card.innerHTML = `
      <div class="completion-guard-header">
        <span class="completion-guard-title">🛡️ Completion Guard</span>
        <span class="completion-guard-status">Checking...</span>
      </div>
      <div class="completion-guard-body">
        <div class="completion-guard-summary">Reviewing whether this response needs a repair pass.</div>
      </div>
    `;
    messageEl.appendChild(card);
    return card;
  }

  _updateCompletionGuardCard(data) {
    const messageId = data?.message_id;
    if (!messageId) return;

    const card = this.messagesContainer.querySelector(`.completion-guard-card[data-message-id="${messageId}"]`)
      || this._ensureCompletionGuardCard(messageId, data?.conversation_id);
    if (!card) return;

    const ensureBody = () => {
      let body = card.querySelector('.completion-guard-body');
      if (!body) {
        body = document.createElement('div');
        body.className = 'completion-guard-body';
        card.appendChild(body);
      }

      let summary = body.querySelector('.completion-guard-summary');
      if (!summary) {
        summary = document.createElement('div');
        summary.className = 'completion-guard-summary';
        body.appendChild(summary);
      }

      return { body, summary };
    };

    const { body, summary } = ensureBody();
    const statusEl = card.querySelector('.completion-guard-status');
    const summaryEl = summary;
    const noteEl = body.querySelector('.completion-guard-note');
    const yesBtn = card.querySelector('.completion-guard-yes');
    const noBtn = card.querySelector('.completion-guard-no');
    const noteInput = card.querySelector('.completion-guard-note-input');
    const renderResolvedBody = (summaryText, noteText = '', ticketPath = '') => {
      body.innerHTML = `
        <div class="completion-guard-summary">${Utils.escapeHtml(summaryText || '')}</div>
        ${noteText ? `<div class="completion-guard-note">Note: ${Utils.escapeHtml(noteText)}</div>` : ''}
        ${ticketPath ? `<div class="completion-guard-ticket">Ticket: <code>${Utils.escapeHtml(ticketPath)}</code></div>` : ''}
      `;
    };

    if (data.status === 'expired' || data.status === 'superseded') {
      this._markCompletionGuardCardInactive(card, data.status, data.reason || '');
      return;
    }

    if (data.status === 'accepted') {
      card.classList.remove('submitting');
      card.classList.add('resolved');
      if (statusEl) statusEl.textContent = 'Accepted';
      renderResolvedBody(
        'Marked as completed correctly.',
        data.note || noteInput?.value || ''
      );
      return;
    }

    if (data.status === 'repairing') {
      this._clearMessageResponseActions();
      card.classList.add('submitting');
      card.classList.remove('resolved');
      if (statusEl) statusEl.textContent = 'Repairing...';
      if (summaryEl) {
        summaryEl.textContent = data.auto_triggered
          ? 'Auto-check found a likely issue. Trying one follow-up pass using the existing task context.'
          : 'Trying one follow-up pass using the existing task context.';
      }
      if (yesBtn) yesBtn.disabled = true;
      if (noBtn) noBtn.disabled = true;
      if (noteInput) noteInput.disabled = true;
      return;
    }

    if (data.status === 'repaired') {
      card.classList.remove('submitting');
      card.classList.add('resolved');
      if (statusEl) statusEl.textContent = 'Repaired';
      renderResolvedBody(
        'A repair pass found a better answer and added it below.',
        data.note || noteInput?.value || ''
      );
      if (yesBtn) yesBtn.disabled = true;
      if (noBtn) noBtn.disabled = true;
      if (noteInput) noteInput.disabled = true;
      return;
    }

    if (data.status === 'tighten_only') {
      card.classList.remove('submitting');
      card.classList.add('resolved');
      if (statusEl) statusEl.textContent = 'Tightened only';
      renderResolvedBody(
        'Completion Guard reviewed this response, but only found wording-level cleanup. No material evidence or tool-path improvement was surfaced as a separate repair.',
        data.note || noteInput?.value || ''
      );
      if (yesBtn) yesBtn.disabled = false;
      if (noBtn) noBtn.disabled = false;
      if (noteInput) noteInput.disabled = false;
      return;
    }

    if (data.status === 'cancelled') {
      card.classList.remove('submitting');
      card.classList.remove('resolved');
      if (statusEl) statusEl.textContent = 'Cancelled';
      renderResolvedBody(
        'Repair was stopped before it finished. You can leave this response as-is or trigger another repair later.',
        data.note || noteInput?.value || ''
      );
      if (yesBtn) yesBtn.disabled = false;
      if (noBtn) noBtn.disabled = false;
      if (noteInput) noteInput.disabled = false;
      return;
    }

    if (data.status === 'unresolved') {
      card.classList.remove('submitting');
      if (statusEl) statusEl.textContent = 'Unresolved';
      renderResolvedBody(
        data.ticket_path
          ? 'One repair pass could not fully resolve this, so it was logged for follow-up.'
          : 'One repair pass could not fully resolve this response.',
        data.note || noteInput?.value || '',
        data.ticket_path || ''
      );
      if (yesBtn) yesBtn.disabled = true;
      if (noBtn) noBtn.disabled = true;
      if (noteInput) noteInput.disabled = true;
      return;
    }

    if (data.status === 'ticket_created') {
      card.classList.remove('submitting');
      card.classList.add('resolved');
      if (statusEl) statusEl.textContent = 'Ticket created';
      renderResolvedBody(
        'Marked incomplete and logged for follow-up.',
        data.note || noteInput?.value || '',
        data.ticket_path || ''
      );
      if (yesBtn) yesBtn.disabled = true;
      if (noBtn) noBtn.disabled = true;
      if (noteInput) {
        noteInput.disabled = true;
      }
      return;
    }

    if (data.status === 'noted') {
      card.classList.remove('submitting');
      card.classList.add('resolved');
      if (statusEl) statusEl.textContent = 'Noted';
      renderResolvedBody(
        'Saved your completion note.',
        data.note || noteInput?.value || ''
      );
      return;
    }

    if (data.status === 'error') {
      card.classList.remove('submitting');
      if (statusEl) statusEl.textContent = 'Error';
      if (summaryEl) summaryEl.textContent = data.error || 'Completion Guard failed.';
      if (yesBtn) yesBtn.disabled = false;
      if (noBtn) noBtn.disabled = false;
      if (noteInput) noteInput.disabled = false;
    }
  }

  _clearMessageResponseActions() {
    this.messagesContainer.querySelectorAll('.message-response-actions').forEach((actions) => {
      actions.remove();
    });
  }

  _attachMessageResponseActions(messageEl, responseText, data = {}, options = {}) {
    const innerData = data.data || data || {};
    const eligible = options.allowReaction !== false && (
      data.human_reaction_eligible === true
      || innerData._human_reaction_eligible === true
    );
    const messageId = data.message_id || innerData._web_message_id || '';
    const conversationId = data.conversation_id
      || innerData.conversation_id
      || window.jarvisSocket?.conversationId
      || '';
    const reactionAvailable = eligible && Boolean(messageId) && Boolean(conversationId);
    const canvasAvailable = options.allowCanvas !== false;
    const userMessages = this.messagesContainer.querySelectorAll('.message.user');
    const userMessage = userMessages[userMessages.length - 1];
    const userText = userMessage?._jarvisMarkdownContent
      || userMessage?.querySelector('.message-bubble')?.textContent?.trim()
      || '';
    if (!userText || !responseText) return;

    const actions = document.createElement('div');
    actions.className = 'message-response-actions';
    actions.dataset.messageId = messageId;
    actions.dataset.conversationId = conversationId;
    actions.innerHTML = `
      <button type="button" class="message-response-action-btn message-copy-btn" title="Copy latest question and response as Markdown" aria-label="Copy latest question and response as Markdown">
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <rect x="8" y="8" width="12" height="12" rx="2"></rect>
          <path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"></path>
        </svg>
      </button>
      ${canvasAvailable ? `
        <button type="button" class="message-response-action-btn send-to-canvas-btn" title="Send this response to Canvas" aria-label="Send this response to Canvas">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M6 3h8l4 4v14H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Z"></path>
            <path d="M14 3v5h5M8 13h6M8 17h6"></path>
          </svg>
        </button>
      ` : ''}
      ${reactionAvailable ? `
        <button type="button" class="message-response-action-btn message-intelligence-action-start" data-reaction="up" title="I like this response — promote it for Intelligence" aria-label="I like this response — promote it for Intelligence">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M7 22H3V9h4v13Zm2-13 5-7c.6-.8 2-.4 2 1v5h4c1.2 0 2.1 1.1 1.8 2.3l-2 9A2.2 2.2 0 0 1 17.7 21H9V9Z"></path>
          </svg>
        </button>
        <button type="button" class="message-response-action-btn" data-reaction="down" title="I dislike this response — prioritize it for Intelligence review" aria-label="I dislike this response — prioritize it for Intelligence review">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M7 2H3v13h4V2Zm2 13 5 7c.6.8 2 .4 2-1v-5h4c1.2 0 2.1-1.1 1.8-2.3l-2-9A2.2 2.2 0 0 0 17.7 3H9v12Z"></path>
          </svg>
        </button>
        <span class="message-reaction-status" aria-live="polite"></span>
      ` : ''}
    `;

    actions.querySelector('.message-copy-btn')?.addEventListener('click', (event) => {
      this._copyLatestExchangeAsMarkdown(event.currentTarget, userText, responseText);
    });

    actions.querySelector('.send-to-canvas-btn')?.addEventListener('click', (event) => {
      this.sendResponseToCanvas(responseText, event.currentTarget);
    });

    actions.querySelectorAll('[data-reaction]').forEach((button) => {
      button.addEventListener('click', () => {
        if (actions.classList.contains('submitting')) return;
        actions.classList.add('submitting');
        actions.querySelectorAll('[data-reaction]').forEach((item) => {
          item.disabled = true;
        });
        window.jarvisSocket.emit('message_reaction:submit', {
          message_id: messageId,
          conversation_id: conversationId,
          reaction: button.dataset.reaction
        });
      });
    });

    messageEl.appendChild(actions);
  }

  async _copyLatestExchangeAsMarkdown(button, userText, responseText) {
    const markdown = `## User\n\n${String(userText).trim()}\n\n## Jarvis\n\n${String(responseText).trim()}\n`;
    const originalHtml = button.innerHTML;
    const originalTitle = button.title;

    try {
      let copied = false;
      let clipboardError = null;
      if (window.isSecureContext
          && navigator.clipboard
          && typeof navigator.clipboard.writeText === 'function') {
        try {
          await navigator.clipboard.writeText(markdown);
          copied = true;
        } catch (error) {
          clipboardError = error;
        }
      }

      if (!copied) {
        try {
          Utils.copyTextFallback(markdown);
          copied = true;
        } catch (fallbackError) {
          throw clipboardError || fallbackError;
        }
      }

      button.classList.add('copied');
      button.disabled = true;
      button.title = 'Copied as Markdown';
      button.setAttribute('aria-label', 'Copied as Markdown');
      button.innerHTML = `
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="m5 12 4 4L19 6"></path>
        </svg>
      `;
      Utils.toast('Copied latest exchange as Markdown', 'success', 1800);

      setTimeout(() => {
        button.classList.remove('copied');
        button.disabled = false;
        button.title = originalTitle;
        button.setAttribute('aria-label', originalTitle);
        button.innerHTML = originalHtml;
      }, 1400);
    } catch (error) {
      console.error('[Chat] Failed to copy latest exchange:', error);
      Utils.toast('Could not copy the latest exchange', 'error', 3000);
    }
  }

  _updateMessageReactionActions(data = {}) {
    const messageId = data.message_id || '';
    const actions = this.messagesContainer.querySelector(
      `.message-response-actions[data-message-id="${messageId}"]`
    );
    if (!actions) return;

    actions.classList.remove('submitting');
    actions.classList.add('recorded');
    actions.querySelectorAll('[data-reaction]').forEach((button) => {
      const selected = button.dataset.reaction === data.reaction;
      button.classList.toggle('selected', selected);
      button.disabled = true;
      button.setAttribute('aria-pressed', selected ? 'true' : 'false');
    });
    const status = actions.querySelector('.message-reaction-status');
    if (status) status.textContent = 'Saved for Intelligence';
    if (!data.restored) Utils.toast(
      data.reaction === 'up'
        ? 'Helpful response promoted for Intelligence'
        : 'Response marked unsatisfactory for Intelligence',
      data.reaction === 'up' ? 'success' : 'info',
      3000
    );
  }

  _handleMessageReactionError(data = {}) {
    const messageId = data.message_id || '';
    const actions = this.messagesContainer.querySelector(
      `.message-response-actions[data-message-id="${messageId}"]`
    );
    if (actions) {
      actions.classList.remove('submitting');
      actions.querySelectorAll('[data-reaction], .message-reaction-status').forEach((item) => {
        item.remove();
      });
    }

    const quietReasons = new Set([
      'reflection_not_pending',
      'not_latest_live_response',
      'reaction_not_available',
      'already_reacted'
    ]);
    if (!quietReasons.has(data.reason)) {
      Utils.toast('Could not save response feedback', 'error', 3000);
    }
  }

  /**
   * Add error message to chat
   */
  addErrorMessage(error) {
    const messageEl = document.createElement('div');
    messageEl.className = 'message assistant';
    messageEl.innerHTML = `
      <div class="message-bubble" style="border-color: var(--error); background: var(--error-bg);">
        <strong>⚠️ Error:</strong> ${Utils.escapeHtml(error)}
      </div>
    `;
    
    this.messagesContainer.appendChild(messageEl);
    Utils.scrollToBottom(this.messagesContainer);
  }

  /**
   * Show thinking indicator
   */
  showThinking() {
    // Reuse the container: live tool cards are nested beneath it.
    if (this.messagesContainer.querySelector('.thinking-message')) {
      if (this.stopBtn) this.stopBtn.style.display = 'flex';
      return;
    }
    
    // Show stop button
    if (this.stopBtn) {
      this.stopBtn.style.display = 'flex';
    }
    
    const thinkingEl = document.createElement('div');
    thinkingEl.className = 'message assistant thinking-message';
    thinkingEl.innerHTML = `
      <div class="thinking-indicator" data-phase="thinking">
        <svg class="processing-glyph" viewBox="0 0 32 32" aria-hidden="true" focusable="false">
          <defs>
            <linearGradient id="sc-grad-outer" x1="0" y1="0" x2="1" y2="1">
              <stop class="processing-glyph__stop--a" offset="0"></stop>
              <stop class="processing-glyph__stop--b" offset="0.55"></stop>
              <stop class="processing-glyph__stop--c" offset="1"></stop>
            </linearGradient>
            <linearGradient id="sc-grad-inner" x1="1" y1="0" x2="0" y2="1">
              <stop class="processing-glyph__stop--c" offset="0"></stop>
              <stop class="processing-glyph__stop--a" offset="1"></stop>
            </linearGradient>
            <radialGradient id="sc-grad-core">
              <stop class="processing-glyph__stop--hot" offset="0"></stop>
              <stop class="processing-glyph__stop--b" offset="0.55"></stop>
              <stop class="processing-glyph__stop--fade" offset="1"></stop>
            </radialGradient>
          </defs>
          <circle class="processing-glyph__track" cx="16" cy="16" r="12" pathLength="100"></circle>
          <circle class="processing-glyph__echo" cx="16" cy="16" r="4.5" pathLength="100"></circle>
          <g class="processing-glyph__orbit processing-glyph__orbit--outer">
            <circle class="processing-glyph__arc processing-glyph__arc--outer" cx="16" cy="16" r="12" pathLength="100"></circle>
            <circle class="processing-glyph__comet" cx="16" cy="4" r="1.7"></circle>
          </g>
          <g class="processing-glyph__orbit processing-glyph__orbit--inner">
            <circle class="processing-glyph__arc processing-glyph__arc--inner" cx="16" cy="16" r="7.5" pathLength="100"></circle>
          </g>
          <path class="processing-glyph__scan" d="M7.5 16h17"></path>
          <circle class="processing-glyph__aura" cx="16" cy="16" r="5.4"></circle>
          <circle class="processing-glyph__core" cx="16" cy="16" r="2.7"></circle>
        </svg>
        <span class="thinking-label">Thinking</span>
      </div>
      <div class="tool-cards" id="pendingToolCards"></div>
    `;
    
    this.messagesContainer.appendChild(thinkingEl);
    Utils.scrollToBottom(this.messagesContainer);
  }

  /**
   * Hide thinking indicator
   */
  hideThinking() {
    this._resetProcessingPhase();
    const thinkingEl = this.messagesContainer.querySelector('.thinking-message');
    if (thinkingEl) {
      thinkingEl.querySelectorAll('video').forEach(video => video.pause?.());
      thinkingEl.remove();
    }
    
    // Hide and reset stop button
    if (this.stopBtn) {
      this.stopBtn.style.display = 'none';
      this.stopBtn.disabled = false;
      this.stopBtn.style.opacity = '1';
    }
  }

  _processingToolKey(data = {}) {
    const messageId = data.message_id || this.currentMessageId || 'current';
    const callId = data.call_index ?? data.workflow_step ?? 0;
    return `${messageId}:${data.tool || 'tool'}:${callId}`;
  }

  _setProcessingLabel(label) {
    const labelEl = this.messagesContainer.querySelector('.thinking-label');
    if (labelEl) labelEl.textContent = label;
  }

  _setProcessingPhase(phase, label) {
    const indicatorEl = this.messagesContainer.querySelector('.thinking-indicator');
    if (indicatorEl) indicatorEl.dataset.phase = phase;
    this._setProcessingLabel(label);
  }

  _markToolStarted(data = {}) {
    this.activeToolCalls.add(this._processingToolKey(data));
    if (this.activeToolCalls.size !== 1) return;

    if (this._workingLabelTimer) clearTimeout(this._workingLabelTimer);
    this._workingLabelTimer = setTimeout(() => {
      this._workingLabelTimer = null;
      if (this.activeToolCalls.size === 0) return;
      this._workingLabelVisible = true;
      this._setProcessingPhase('working', 'Working');
    }, this.processingPhaseDelayMs);
  }

  _markToolFinished(data = {}) {
    this.activeToolCalls.delete(this._processingToolKey(data));
    if (this.activeToolCalls.size > 0) return;

    if (this._workingLabelTimer) {
      clearTimeout(this._workingLabelTimer);
      this._workingLabelTimer = null;
    }
    if (this._workingLabelVisible) {
      this._workingLabelVisible = false;
      this._setProcessingPhase('reviewing', 'Reviewing results');
    }
  }

  _resetProcessingPhase() {
    if (this._workingLabelTimer) {
      clearTimeout(this._workingLabelTimer);
      this._workingLabelTimer = null;
    }
    this.activeToolCalls.clear();
    this._workingLabelVisible = false;
  }

  _resetProcessingUi() {
    this.hideThinking();
    this.clearStatus();
    this.isProcessing = false;
    this.updateSendButton();
  }

  rememberRenderedMessage(role, id) {
    this._renderedMessageIds ||= new Set();
    if (id) this._renderedMessageIds.add(`${role}:${id}`);
  }

  reconcileLiveActions(conversation) {
    for (const message of conversation.messages || []) {
      const data = message.data || {};
      const id = data._web_message_id;
      if (!id) continue;
      if (id !== conversation.reaction_message_id && !data._user_feedback) {
        const actions = this.messagesContainer.querySelector(`.message-response-actions[data-message-id="${id}"]`);
        actions?.querySelectorAll('[data-reaction], .message-reaction-status').forEach(item => item.remove());
      }
      if (data._completion_guard?.status === 'pending' && !conversation.completion_guards?.[id]
          && this.messagesContainer.querySelector(`.completion-guard-card[data-message-id="${id}"]`)) {
        this._updateCompletionGuardCard({message_id: id, status: 'expired'});
      }
    }
  }

  restoreRunState(run, { fromSnapshot = false, responseSaved = false, preservePreparation = false } = {}) {
    const active = run && ['running', 'stopping'].includes(run.status);
    if (!fromSnapshot && !active && run?.message_id && this.currentMessageId
        && run.message_id !== this.currentMessageId) return;
    if (!fromSnapshot && run?.started_at < this._serverRunState?.started_at) return;
    this._serverRunState = run || null;
    if (preservePreparation && (this._attachmentSend || this._imageUpload)) {
      this.stopBtn.disabled = !window.jarvisSocket.connected;
      this.stopBtn.style.opacity = this.stopBtn.disabled ? '0.5' : '1';
      this.showProgressStatus('Preparing attached sources…');
      return;
    }
    if (!fromSnapshot && active && this.currentMessageId !== run.message_id) {
      // Another tab started a task. Load its user turn as well as its state.
      window.jarvisApp?.loadConversation(run.conversation_id);
      return;
    }
    if (active) {
      const alreadyVisible = this.isProcessing && this.currentMessageId === run.message_id;
      this.currentMessageId = run.message_id;
      this.isProcessing = true;
      this.updateSendButton();
      if (!alreadyVisible) this.showThinking();
      this.showProgressStatus(run.status === 'stopping' ? 'Stopping…' : (run.status_text || 'Working…'));
      this.stopBtn.disabled = run.status === 'stopping' || !window.jarvisSocket.connected;
      this.stopBtn.style.opacity = this.stopBtn.disabled ? '0.5' : '1';
    } else {
      this._resetProcessingUi();
      this.currentMessageId = null;
      if (fromSnapshot && !responseSaved && run && ['failed', 'interrupted'].includes(run.status)) {
        this.addErrorMessage(run.error || 'This task did not finish successfully.');
      }
    }
    if (run?.persistence_error) Utils.toast(run.persistence_error, 'error', 10000);
  }

  /**
   * Show an ephemeral status message (progress update)
   * Delayed by 1 second to sync with TTS audio playback
   */
  showStatus(statusText) {
    // Clear any pending status timeout
    if (this._statusTimeout) {
      clearTimeout(this._statusTimeout);
    }
    
    // Delay showing status to sync with TTS playback
    this._statusTimeout = setTimeout(() => {
      // Remove existing status
      const existingStatus = this.messagesContainer.querySelector('.status-message');
      if (existingStatus) {
        existingStatus.remove();
      }
      
      const statusEl = document.createElement('div');
      statusEl.className = 'message status-message';
      statusEl.innerHTML = `
        <div class="status-content">
          <span class="status-icon">💬</span>
          <span class="status-text">${Utils.escapeHtml(statusText)}</span>
        </div>
      `;
      
      this.messagesContainer.appendChild(statusEl);
      Utils.scrollToBottom(this.messagesContainer);
      
      // Auto-remove after 10 seconds (will be replaced by next status or final response)
      setTimeout(() => {
        if (statusEl.parentNode) {
          statusEl.classList.add('fade-out');
          setTimeout(() => statusEl.remove(), 300);
        }
      }, 10000);
    }, 1000);  // 1 second delay to sync with TTS
  }
  
  /**
   * Show instant progress status (no delay, shorter duration)
   * Used for routing/tool execution progress events
   */
  showProgressStatus(statusText) {
    // Remove existing progress status
    const existingProgress = this.messagesContainer.querySelector('.progress-status-message');
    if (existingProgress) {
      existingProgress.remove();
    }
    
    const statusEl = document.createElement('div');
    statusEl.className = 'message progress-status-message';
    statusEl.innerHTML = `
      <div class="progress-status-content">
        <span class="progress-icon">⚡</span>
        <span class="progress-text">${Utils.escapeHtml(statusText)}</span>
      </div>
    `;
    
    this.messagesContainer.appendChild(statusEl);
    Utils.scrollToBottom(this.messagesContainer);
    
    // Auto-remove after 5 seconds (or replaced by next progress/response)
    setTimeout(() => {
      if (statusEl.parentNode) {
        statusEl.classList.add('fade-out');
        setTimeout(() => statusEl.remove(), 300);
      }
    }, 5000);
  }
  
  /**
   * Clear status message
   */
  clearStatus() {
    // Clear pending status timeout
    if (this._statusTimeout) {
      clearTimeout(this._statusTimeout);
      this._statusTimeout = null;
    }
    
    // Clear TTS status message
    const statusEl = this.messagesContainer.querySelector('.status-message');
    if (statusEl) {
      statusEl.remove();
    }
    
    // Clear progress status message
    const progressEl = this.messagesContainer.querySelector('.progress-status-message');
    if (progressEl) {
      progressEl.remove();
    }
  }

  /**
   * Add a tool execution card (for tool:start events)
   * @param {string} cardId - Unique ID for the card (e.g., 'crypto_price' or 'phone_call_1')
   * @param {string} toolName - Display name of the tool
   * @param {string} status - Status: 'pending', 'success', 'error', 'skipped'
   * @param {object} args - Tool arguments
   */
  addToolCard(cardId, toolName, status, args = {}) {
    // Store in pendingTools using cardId as key
    this.pendingTools[cardId] = { toolName, status, args, result: null, duration: null };
    
    const pendingCards = document.getElementById('pendingToolCards');
    if (!pendingCards) return;
    
    const cardHtml = this._createToolCardHtml(toolName, status, args);
    const cardEl = document.createElement('div');
    cardEl.innerHTML = cardHtml;
    cardEl.firstChild.id = `tool-card-${cardId}`;
    
    pendingCards.appendChild(cardEl.firstChild);
    Utils.scrollToBottom(this.messagesContainer);
  }

  /**
   * Update a tool card (creates it if doesn't exist - for workflows)
   * @param {string} cardId - Unique ID for the card (may include step number for workflows)
   * @param {string} toolName - Display name of the tool
   * @param {string} status - Status: 'pending', 'success', 'error', 'skipped'
   * @param {object} result - Tool result data
   * @param {number} duration - Duration in ms
   */
  updateToolCard(cardId, toolName, status, result = {}, duration = null) {
    // Handle legacy calls with 4 args (cardId = toolName)
    if (
      typeof toolName !== 'string'
      || ['pending', 'success', 'error', 'skipped'].includes(toolName)
    ) {
      // Legacy call: updateToolCard(toolName, status, result, duration)
      duration = result;
      result = status;
      status = toolName;
      toolName = cardId;
      // cardId already equals toolName
    }
    
    // Store in pendingTools
    if (!this.pendingTools[cardId]) {
      this.pendingTools[cardId] = { toolName, status, args: {}, result: null, duration: null };
    }
    this.pendingTools[cardId].status = status;
    this.pendingTools[cardId].result = result;
    this.pendingTools[cardId].duration = duration;
    
    let card = document.getElementById(`tool-card-${cardId}`);
    
    // Create card if it doesn't exist (workflow case - no tool:start event)
    if (!card) {
      const pendingCards = document.getElementById('pendingToolCards');
      if (!pendingCards) return;
      
      const cardHtml = this._createToolCardHtml(toolName, status, result, duration);
      const cardEl = document.createElement('div');
      cardEl.innerHTML = cardHtml;
      cardEl.firstChild.id = `tool-card-${cardId}`;
      
      pendingCards.appendChild(cardEl.firstChild);
      Utils.scrollToBottom(this.messagesContainer);
      return;
    }
    
    const videoAnalysisHtml = toolName === 'analyze_video' ? this._renderVideoAnalysisResult(result) : null;
    card.className = `tool-card ${status}${videoAnalysisHtml ? ' expanded' : ''}`;
    
    const statusEl = card.querySelector('.tool-card-status');
    if (statusEl) {
      if (status === 'success') {
        statusEl.innerHTML = videoAnalysisHtml && (result.data?.partial ?? result.partial) === true
          ? '⚠️ Partial analysis'
          : `✅ ${duration ? Utils.formatDuration(duration) : 'Complete'}`;
      } else if (status === 'error') {
        statusEl.innerHTML = `❌ Failed`;
      } else if (status === 'skipped') {
        statusEl.innerHTML = `⏭ Skipped`;
      } else if (result.progress !== undefined) {
        statusEl.innerHTML = `⏳ ${result.progress}%`;
      }
    }
    
    const bodyEl = card.querySelector('.tool-card-body');
    if (bodyEl && result) {
      if (videoAnalysisHtml) {
        bodyEl.querySelectorAll('video').forEach(video => video.pause?.());
        bodyEl.innerHTML = videoAnalysisHtml;
      } else {
        const summary = typeof result === 'object' ? Utils.formatJson(result) : String(result);
        bodyEl.innerHTML = Utils.escapeHtmlAndLinkify(summary);
      }
    }
  }

  /** Keep a bounded, readable timeline for a live OpenCode session. */
  _updateOpenCodeProgressCard(cardId, data) {
    if (!this.pendingTools[cardId]) {
      this.updateToolCard(cardId, 'opencode', 'pending', {});
    }

    const state = this.pendingTools[cardId];
    state.progressEvents = Array.isArray(state.progressEvents) ? state.progressEvents : [];
    const previous = state.progressEvents[state.progressEvents.length - 1];
    if (!previous || previous.status !== data.status || previous.phase !== data.phase) {
      state.progressEvents.push({
        status: data.status,
        phase: data.phase || 'running'
      });
      state.progressEvents = state.progressEvents.slice(-8);
    }
    if (data.session_id) state.sessionId = data.session_id;

    const card = document.getElementById(`tool-card-${cardId}`);
    if (!card) return;

    const statusEl = card.querySelector('.tool-card-status');
    if (statusEl) {
      const icon = data.phase === 'error' || data.phase === 'blocked'
        ? '⚠️'
        : data.phase === 'complete'
          ? '✅'
          : '⏳';
      const percent = Number.isFinite(data.progress) ? ` ${data.progress}%` : '';
      statusEl.textContent = `${icon}${percent} ${data.status}`;
    }

    const bodyEl = card.querySelector('.tool-card-body');
    if (bodyEl) {
      bodyEl.textContent = state.progressEvents
        .map((entry) => `• ${entry.status}`)
        .join('\n');
    }

    if (state.sessionId && !card.querySelector('.tool-card-link-row')) {
      const sessionUrl = this._getOpenCodeSessionUrl(state.sessionId);
      if (sessionUrl) {
        const row = document.createElement('div');
        row.className = 'tool-card-link-row';
        const link = document.createElement('a');
        link.href = sessionUrl;
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        link.className = 'content-link tool-card-link';
        link.textContent = `Open session: ${state.sessionId}`;
        row.appendChild(link);
        card.insertBefore(row, bodyEl || null);
      }
    }
  }

  /**
   * Create tool card HTML
   */
  _createToolCardHtml(toolName, status, data, duration = null) {
    const videoAnalysisHtml = toolName === 'analyze_video' ? this._renderVideoAnalysisResult(data) : null;
    const statusText = status === 'pending'
      ? '⏳ Running...'
      : status === 'success'
        ? videoAnalysisHtml && (data.data?.partial ?? data.partial) === true
          ? '⚠️ Partial analysis'
          : `✅ ${duration ? Utils.formatDuration(duration) : 'Complete'}`
        : status === 'skipped'
          ? '⏭ Skipped'
          : '❌ Failed';
    
    // Show full JSON - user can scroll in expanded view
    let summary = '';
    if (videoAnalysisHtml) {
      summary = '';
    } else if (data && typeof data === 'object') {
      summary = Utils.formatJson(data);
    } else if (data) {
      summary = String(data);
    }

    let detailsLinkHtml = '';
    if (toolName === 'opencode' && data && typeof data === 'object' && data.session_id) {
      const sessionUrl = this._getOpenCodeSessionUrl(data.session_id);
      if (sessionUrl) {
        detailsLinkHtml = `
          <div class="tool-card-link-row">
            <a href="${Utils.escapeHtml(sessionUrl)}" target="_blank" rel="noopener noreferrer" class="content-link tool-card-link">
              Open session: ${Utils.escapeHtml(data.session_id)}
            </a>
          </div>
        `;
      }
    }
    
    return `
      <div class="tool-card ${status}${videoAnalysisHtml ? ' expanded' : ''}">
        <div class="tool-card-header">
          <span class="tool-card-title">${Utils.escapeHtml(toolName === 'analyze_video' ? 'Video analysis' : toolName)}</span>
          <span class="tool-card-status">${statusText}</span>
        </div>
        ${detailsLinkHtml}
        ${toolName === 'analyze_video'
          ? `<div class="tool-card-body video-analysis-result">${videoAnalysisHtml || Utils.escapeHtmlAndLinkify(summary)}</div>`
          : `<pre class="tool-card-body">${Utils.escapeHtmlAndLinkify(summary)}</pre>`}
      </div>
    `;
  }

  _getToolResultForOccurrence(toolResultsData, toolName, occurrenceIndex = 0, fallback = null) {
    const namedResult = toolResultsData && toolResultsData[toolName];
    if (Array.isArray(namedResult)) {
      if (occurrenceIndex < namedResult.length) {
        return namedResult[occurrenceIndex] ?? {};
      }
      return namedResult.length > 0 ? (namedResult[namedResult.length - 1] ?? {}) : {};
    }
    if (namedResult !== undefined && namedResult !== null) {
      return namedResult;
    }
    if (
      fallback
      && typeof fallback === 'object'
      && !Array.isArray(fallback)
      && Object.keys(fallback).length === 0
    ) {
      return {};
    }
    return fallback ?? {};
  }

  _getPendingToolCardEntries(toolResultsData = {}, pendingToolEntries = Object.entries(this.pendingTools)) {
    const toolOccurrenceCounts = {};
    const successfulToolOccurrenceCounts = {};
    return pendingToolEntries.map(([cardId, toolData]) => {
      const displayName = toolData.toolName || cardId.replace(/_step\d+$/, '');
      const occurrenceIndex = toolOccurrenceCounts[displayName] || 0;
      toolOccurrenceCounts[displayName] = occurrenceIndex + 1;
      const status = toolData.status || 'success';
      const resultOccurrenceIndex = successfulToolOccurrenceCounts[displayName] || 0;
      if (status !== 'error' && status !== 'skipped') {
        successfulToolOccurrenceCounts[displayName] = resultOccurrenceIndex + 1;
      }
      const result = status === 'error' || status === 'skipped'
        ? (toolData.result ?? {})
        : this._getToolResultForOccurrence(
          toolResultsData,
          displayName,
          resultOccurrenceIndex,
          toolData.result
        );
      return {
        displayName,
        status,
        result,
        duration: toolData.duration
      };
    });
  }

  _getToolTraceEntries(toolResultsData = {}) {
    const trace = toolResultsData?._tool_trace || toolResultsData?.data?._tool_trace;
    const directEntries = Array.isArray(trace)
      ? trace.filter(entry => entry && typeof entry === 'object' && entry.tool)
      : [];
    const workflowRuns = this._getWorkflowRunPayloads(toolResultsData);

    if (!directEntries.length) {
      return workflowRuns.flatMap(workflow => (
        this._getWorkflowStepTraceEntries(toolResultsData, workflow)
      ));
    }
    if (!workflowRuns.length) return directEntries;

    // Autonomous runs can mix workflow meta-tool calls with ordinary tools.
    // Keep that outer trace authoritative, expanding each workflow's component
    // steps at the run call instead of replacing the complete call sequence.
    const unplacedRuns = [...workflowRuns];
    const mergedEntries = [];
    for (const entry of directEntries) {
      mergedEntries.push(entry);
      const argumentsData = entry.arguments && typeof entry.arguments === 'object'
        ? entry.arguments
        : {};
      const isWorkflowRun = entry.tool === 'workflow' && (
        entry.workflow_run_started === true || argumentsData.action === 'run'
      );
      if (!isWorkflowRun) continue;

      const requestedWorkflowId = String(argumentsData.workflow_id || '').trim();
      let workflowIndex = requestedWorkflowId
        ? unplacedRuns.findIndex(workflow => (
          String(workflow?.workflow_id || '').trim() === requestedWorkflowId
        ))
        : 0;
      if (workflowIndex < 0 && unplacedRuns.length === 1) workflowIndex = 0;
      if (workflowIndex < 0) continue;

      const [workflow] = unplacedRuns.splice(workflowIndex, 1);
      mergedEntries.push(...this._getWorkflowStepTraceEntries(toolResultsData, workflow));
    }
    return mergedEntries;
  }

  _getWorkflowRunPayloads(toolResultsData = {}) {
    const workflows = [];
    if (toolResultsData?.workflow_id && Array.isArray(toolResultsData?.results)) {
      workflows.push(toolResultsData);
    }

    const containers = [toolResultsData, toolResultsData?.data];
    for (const container of containers) {
      const nested = container?.workflow;
      const candidates = Array.isArray(nested) ? nested : [nested];
      for (const candidate of candidates) {
        if (
          candidate
          && typeof candidate === 'object'
          && candidate.action === 'run'
          && Array.isArray(candidate.results)
          && !workflows.includes(candidate)
        ) workflows.push(candidate);
      }
    }
    return workflows;
  }

  _getWorkflowStepTraceEntries(toolResultsData = {}, selectedWorkflow = null) {
    let workflowData = selectedWorkflow;
    if (!workflowData) {
      const workflows = this._getWorkflowRunPayloads(toolResultsData);
      workflowData = workflows.length > 0 ? workflows[workflows.length - 1] : null;
    }
    if (!workflowData) return [];

    const entries = [];
    for (const step of workflowData.results) {
      if (!step || typeof step !== 'object' || !step.tool) continue;
      // Optional unavailable tools intentionally have no execution card.
      if (step.skip_kind === 'optional_tool_unavailable') continue;

      const outputs = Array.isArray(step.outputs) ? step.outputs : [];
      if (outputs.length > 0) {
        outputs.forEach((output, outputIndex) => {
          const outputData = output && typeof output === 'object' ? output : {};
          entries.push({
            tool: step.tool,
            ok: outputData.ok !== false,
            skipped: outputData.skipped === true,
            duration_ms: outputData.duration_ms ?? step.duration_ms ?? null,
            error: outputData.error || null,
            reason: outputData.reason || null,
            speech: outputData.speech || null,
            workflow_step: step.step != null ? `${step.step}_${outputIndex}` : null
          });
        });
        continue;
      }

      entries.push({
        tool: step.tool,
        ok: step.ok !== false,
        skipped: step.skipped === true,
        duration_ms: step.duration_ms ?? null,
        error: step.error || null,
        reason: step.reason || null,
        speech: step.speech || step.reason || null,
        workflow_step: step.step ?? null
      });
    }
    return entries;
  }

  _getToolTraceFailureResult(entry = {}) {
    return {
      error: entry.error || entry.speech || 'Tool failed',
      arguments: entry.arguments || {}
    };
  }

  _getToolTraceSkippedResult(entry = {}) {
    return entry.reason || entry.speech || 'Condition evaluated to false';
  }

  _getToolTraceSuccessFallback(entry = {}) {
    const fallback = {};
    if (entry.speech) fallback.speech = entry.speech;
    if (entry.arguments) fallback.arguments = entry.arguments;
    return fallback;
  }

  /**
   * Show feedback card in analyzing state
   */
  _showFeedbackCard(status = 'analyzing', messageId = null) {
    const existingCard = this.messagesContainer.querySelector(
      messageId
        ? `.tool-card.feedback[data-message-id="${messageId}"]`
        : '#feedback-card'
    );
    if (existingCard) {
      existingCard.remove();
    }

    let lastMessage = null;
    if (messageId) {
      lastMessage = this.messagesContainer.querySelector(`.message.assistant[data-message-id="${messageId}"]`);
    }
    if (!lastMessage) {
      const messages = this.messagesContainer.querySelectorAll('.message.assistant:not(.thinking-message)');
      lastMessage = messages[messages.length - 1];
    }

    if (!lastMessage) {
      return;
    }
    
    const cardHtml = `<div id="feedback-card" data-message-id="${Utils.escapeHtml(messageId || '')}" class="tool-card feedback pending expanded" style="margin-top: 12px;">
        <div class="tool-card-header" style="cursor: pointer;">
          <span class="expand-indicator" style="margin-right: 6px; transition: transform 0.2s;">▼</span>
          <span class="tool-card-title">📊 Feedback Analysis</span>
          <span class="tool-card-status">⏳ Analyzing...</span>
        </div>
        <div class="tool-card-body">Evaluating response quality, tool selection, and suggestions for improvement...</div>
      </div>`;
    
    const cardEl = document.createElement('div');
    cardEl.innerHTML = cardHtml;
    
    // Append to the last assistant message's bubble or after tool cards
    const toolCards = lastMessage.querySelector('.tool-cards');
    // Use firstElementChild instead of firstChild to skip whitespace text nodes
    const feedbackCard = cardEl.firstElementChild;
    
    if (!feedbackCard) {
      console.error('[Chat] Failed to create feedback card element');
      return;
    }
    
    if (toolCards) {
      toolCards.appendChild(feedbackCard);
    } else {
      const bubble = lastMessage.querySelector('.message-bubble');
      if (bubble) {
        bubble.appendChild(feedbackCard);
      } else {
        lastMessage.appendChild(feedbackCard);
      }
    }
    
    Utils.scrollToBottom(this.messagesContainer);
  }

  /**
   * Update feedback card with results
   */
  _updateFeedbackCard(data) {
    let card = this.messagesContainer.querySelector(
      data?.message_id
        ? `.tool-card.feedback[data-message-id="${data.message_id}"]`
        : '#feedback-card'
    );
    if (!card) {
      if (data?.message_id && !this.messagesContainer.querySelector(`.message.assistant[data-message-id="${data.message_id}"]`)) return;
      this._showFeedbackCard('analyzing', data?.message_id);
      card = this.messagesContainer.querySelector(data?.message_id
        ? `.tool-card.feedback[data-message-id="${data.message_id}"]` : '#feedback-card');
      if (!card) return;
    }
    
    // Update status
    card.classList.remove('pending');
    card.classList.add(data.success ? 'success' : 'error');
    
    const statusEl = card.querySelector('.tool-card-status');
    const bodyEl = card.querySelector('.tool-card-body');
    
    if (data.success) {
      const duration = data.duration_ms ? Utils.formatDuration(data.duration_ms) : '';
      statusEl.textContent = `✅ ${duration}`;
      
      // Build feedback display
      let feedbackHtml = '';
      
      // Rating with stars
      if (data.rating != null) {
        const ratingColor = data.rating >= 5 ? 'var(--success)' : data.rating >= 4 ? 'var(--warning)' : 'var(--error)';
        const stars = '⭐'.repeat(data.rating) + '☆'.repeat(5 - data.rating);
        feedbackHtml += `<div style="font-size: 1.1em; margin-bottom: 8px;"><strong>Rating:</strong> <span style="color: ${ratingColor}">${stars} (${data.rating}/5)</span></div>`;
      }
      
      // Summary
      if (data.summary) {
        feedbackHtml += `<div style="margin-bottom: 8px;"><strong>Summary:</strong> ${Utils.escapeHtml(data.summary)}</div>`;
      }
      
      // Positive feedback
      if (data.positive) {
        feedbackHtml += `<div style="margin-bottom: 8px; color: var(--success);"><strong>✅ What went well:</strong> ${Utils.escapeHtml(data.positive)}</div>`;
      }
      
      // Issues/Suggestions (if any)
      const issues = data.issues || data.suggestions || [];
      if (issues.length > 0) {
        feedbackHtml += '<div style="margin-bottom: 8px;"><strong>⚠️ Issues:</strong><ul style="margin: 4px 0 0 16px; padding: 0; list-style: none;">';
        for (const issue of issues) {
          // Issues can be objects with description, or plain strings
          const issueText = typeof issue === 'object' 
            ? (issue.description || issue.suggestion || JSON.stringify(issue))
            : issue;
          const category = issue.category ? `[${issue.category}] ` : '';
          feedbackHtml += `<li style="margin: 4px 0;">• ${Utils.escapeHtml(category)}${Utils.escapeHtml(issueText)}</li>`;
        }
        feedbackHtml += '</ul></div>';
      }
      
      // Tool ratings
      if (data.tool_ratings && Object.keys(data.tool_ratings).length > 0) {
        feedbackHtml += '<div><strong>Tool Performance:</strong><ul style="margin: 4px 0 0 16px; padding: 0; list-style: none;">';
        for (const [tool, info] of Object.entries(data.tool_ratings)) {
          const toolRating = info.rating || 5;
          const toolStars = '⭐'.repeat(toolRating);
          const note = info.note ? ` - ${Utils.escapeHtml(info.note)}` : '';
          feedbackHtml += `<li style="margin: 2px 0;"><code>${Utils.escapeHtml(tool)}</code>: ${toolStars}${note}</li>`;
        }
        feedbackHtml += '</ul></div>';
      }
      
      if (!feedbackHtml) {
        feedbackHtml = '✅ Perfect execution - no issues found.';
      }
      
      bodyEl.innerHTML = feedbackHtml;
      
      // Card starts expanded (set in HTML), add click handler for collapse/expand
      const header = card.querySelector('.tool-card-header');
      const expandIndicator = card.querySelector('.expand-indicator');
      if (header && !header.dataset.clickHandlerSet) {
        header.dataset.clickHandlerSet = 'true';
        header.addEventListener('click', () => {
          const isExpanded = card.classList.toggle('expanded');
          if (expandIndicator) {
            expandIndicator.style.transform = isExpanded ? 'rotate(0deg)' : 'rotate(-90deg)';
          }
        });
      }
      
      // Show toast with summary (longer duration: 6 seconds)
      const issueCount = issues.length;
      const toastMsg = issueCount > 0 
        ? `📊 Feedback: ${data.rating}/5 - ${issueCount} issue(s) found`
        : `📊 Feedback: ${data.rating}/5 - Perfect! ✅`;
      Utils.toast(toastMsg, data.rating >= 4 ? 'success' : 'warning', 6000);
    } else {
      statusEl.textContent = '❌ Failed';
      bodyEl.textContent = `Error: ${data.error || 'Unknown error'}`;
      Utils.toast('Feedback analysis failed', 'error');
    }
  }

  /**
   * Toggle feedback mode
   */
  toggleFeedback() {
    if (this.chatOnlyEnabled) {
      this.feedbackEnabled = false;
      this._syncFeedbackControl();
      Utils.toast('Turn off Chat only to use Feedback Analysis', 'info', 2200);
      return;
    }

    this.feedbackEnabled = !this.feedbackEnabled;
    this._syncFeedbackControl();

    Utils.toast(
      this.feedbackEnabled ? '📊 Feedback enabled for next message' : '📊 Feedback disabled',
      'info',
      2000
    );
  }

  _syncFeedbackControl() {
    const feedbackBtn = document.getElementById('feedbackBtn');
    if (!feedbackBtn) return;

    const chatOnly = Boolean(this.chatOnlyEnabled);
    feedbackBtn.disabled = chatOnly;
    feedbackBtn.setAttribute('aria-disabled', String(chatOnly));
    feedbackBtn.classList.toggle('active', this.feedbackEnabled && !chatOnly);
    feedbackBtn.title = chatOnly
      ? 'Feedback Analysis unavailable in Chat only'
      : (this.feedbackEnabled
          ? 'Feedback ON - Click to disable'
          : 'Feedback OFF - Click to enable');
  }

  /**
   * Update send button state
   */
  updateSendButton() {
    const dictating = Boolean(this._voiceSession);
    const busy = Boolean(this._talkActive || this.isProcessing || this._conversationLoadPending || window.jarvisSocket?.connected === false);
    this.sendBtn.disabled = !dictating && busy;
    this.sendBtn.textContent = dictating ? '×' : busy ? '⏳' : '➤';
    this.sendBtn.classList.toggle('cancel-dictation', dictating);
    this.sendBtn.title = dictating ? 'Cancel dictation (Esc)' : 'Send Message';
    this.sendBtn.setAttribute('aria-label', dictating ? 'Cancel dictation' : 'Send Message');
    this._syncComposerHint();
  }
  
  /**
   * Cancel current processing
   */
  cancelProcessing() {
    if (this.cancelAttachmentPreparation()) {
      Utils.toast('Attachment preparation stopped. Your draft is ready to retry.', 'info', 3000);
      return;
    }
    if (!this.isProcessing && !this.currentMessageId) return;
    
    console.log('[ChatUI] Canceling processing...');
    
    // Send cancel event to server
    if (!window.jarvisSocket?.cancel(window.jarvisSocket.conversationId, this.currentMessageId)) {
      Utils.toast('Reconnect to Jarvis to stop this task.', 'info', 3000);
      return;
    }
    
    // Show cancellation status
    this.showProgressStatus('Stopping...');
    
    // Disable stop button to prevent spam
    this.stopBtn.disabled = true;
    this.stopBtn.style.opacity = '0.5';
  }

  /**
   * Update token counter display
   * @param {Object} usage - {input_tokens, output_tokens, total_tokens, cost_usd, cache_read_tokens, ...}
   */
  async _updateTokenCounter(usage) {
    if (!this.tokenCounterEl || !usage) return;

    this._accumulateUsage(usage);
    if (usage.provider) {
      const identityChanged = usage.provider !== this.tokenStatsMeta.provider
        || (usage.model && usage.model !== this.tokenStatsMeta.model)
        || (usage.mode && usage.mode !== this.tokenStatsMeta.mode);
      this.tokenStatsLocked = false;
      this.tokenStatsMeta.provider = usage.provider;
      if (usage.model) this.tokenStatsMeta.model = usage.model;
      if (usage.mode) this.tokenStatsMeta.mode = usage.mode;
      this.tokenStatsMeta.billingMode = usage.billing_mode || null;
      if (identityChanged) {
        this.tokenStatsMeta.contextWindow = null;
      }
    }

    this._renderTokenCount();
    this._renderCostLabel();
    this.tokenCounterEl.style.display = 'flex';
    this._renderTokenTooltip();

    if (usage.provider && !this.tokenStatsMeta.contextWindow) {
      const identityKey = `${usage.provider}:${usage.model || ''}:${usage.mode || ''}`;
      const resolved = await this._resolveContextWindowForProviderModel(
        usage.provider,
        usage.model || null,
        usage.mode || null
      );
      const currentIdentityKey = `${this.tokenStatsMeta.provider || ''}:${this.tokenStatsMeta.model || ''}:${this.tokenStatsMeta.mode || ''}`;
      if (resolved && identityKey === currentIdentityKey) {
        this.tokenStatsMeta.contextWindow = resolved;
        this._renderTokenTooltip();
      }
    }
  }

  _accumulateUsage(usage) {
    const inputTokens = usage.input_tokens || 0;
    const outputTokens = usage.output_tokens || 0;
    const totalTokens = usage.total_tokens || (inputTokens + outputTokens);
    const cost = typeof usage.cost_usd === 'number' ? usage.cost_usd : 0;
    const unknownCost = usage.has_unknown_cost === true
      || usage.cost_known === false
      || ['ollama_cloud_subscription', 'xai_oauth_subscription'].includes(usage.billing_mode);

    this.cumulativeTokens.input += inputTokens;
    this.cumulativeTokens.output += outputTokens;
    this.cumulativeTokens.total += totalTokens;
    if (Number.isFinite(usage.model_calls)) {
      this.cumulativeModelCalls += usage.model_calls;
    } else {
      this.modelCallCountComplete = false;
    }
    if (Number.isFinite(usage.peak_context_tokens)) {
      this.currentContextTokens = usage.peak_context_tokens;
      this.currentContextEstimated = false;
    } else {
      // Older saved responses only have an aggregate total. It is the best
      // available approximation, but may span multiple model calls.
      this.currentContextTokens = totalTokens;
      this.currentContextEstimated = true;
    }
    this.cumulativeCost += cost;
    this.cumulativeCache.read += usage.cache_read_tokens || 0;
    this.cumulativeCache.creation += usage.cache_creation_tokens || 0;
    this.cumulativeCache.writeCostUsd += usage.cache_write_cost_usd || 0;
    this.cumulativeCache.readCostUsd += usage.cache_read_cost_usd || 0;
    if (typeof usage.cache_savings_usd === 'number') {
      this.cumulativeCache.savingsUsd += usage.cache_savings_usd;
    }
    if (unknownCost) this.cumulativeUnknownCost = true;
    if (usage.input_estimated === true) this.cumulativeInputEstimated = true;
  }

  /**
   * Render the token count, prefixing "~" when the input tokens were estimated
   * (provider omitted prompt_eval_count, e.g. Ollama Cloud).
   */
  _renderTokenCount() {
    if (!this.tokenCountEl) return;
    const tokenStr = this.cumulativeTokens.total.toLocaleString();
    const prefix = this.cumulativeInputEstimated ? '~' : '';
    this.tokenCountEl.textContent = `${prefix}${tokenStr} tokens`;
  }

  /**
   * Render the cost label, accounting for subscription/compute-metered providers
   * (e.g. Ollama Cloud) where the dollar cost is unknown rather than $0.
   */
  _renderCostLabel() {
    if (!this.tokenCostEl) return;
    if (this.cumulativeCost > 0) {
      this.tokenCostEl.textContent = this.cumulativeCost < 0.01
        ? `$${this.cumulativeCost.toFixed(4)}`
        : `$${this.cumulativeCost.toFixed(2)}`;
    } else if (this.cumulativeUnknownCost) {
      this.tokenCostEl.textContent = 'subscription';
    } else {
      this.tokenCostEl.textContent = '';
    }
  }

  _formatProviderLabel() {
    const provider = this.tokenStatsMeta.provider || this.llmProvider;
    const model = this.tokenStatsMeta.model;
    if (!provider) return '';
    const providerLabel = provider.toUpperCase();
    return model ? `${providerLabel} / ${model}` : providerLabel;
  }

  _renderTokenTooltip() {
    if (!this.tokenCounterEl) return;

    const lines = [];
    lines.push(
      `Chat processed: ${this.cumulativeTokens.input.toLocaleString()} input | ${this.cumulativeTokens.output.toLocaleString()} output`
    );
    if (this.modelCallCountComplete) {
      lines.push(`Model calls: ${this.cumulativeModelCalls.toLocaleString()}`);
    } else if (this.cumulativeModelCalls > 0) {
      lines.push(`Model calls: at least ${this.cumulativeModelCalls.toLocaleString()} (older history unavailable)`);
    } else {
      lines.push('Model calls: unavailable for older history');
    }

    const contextWindow = this.tokenStatsMeta.provider
      ? this.tokenStatsMeta.contextWindow
      : this.contextWindow;
    const providerLabel = this._formatProviderLabel();
    if (Number.isFinite(contextWindow) && contextWindow > 0) {
      const usagePercent = (this.currentContextTokens / contextWindow) * 100;
      const estimatePrefix = this.currentContextEstimated ? '~' : '';
      const contextLine = `Current context: ${estimatePrefix}${this.currentContextTokens.toLocaleString()} / ${contextWindow.toLocaleString()} (${usagePercent.toFixed(1)}%)`;
      this.tokenCounterEl.classList.remove('warning', 'danger');
      if (usagePercent > 80) {
        this.tokenCounterEl.classList.add('danger');
        lines.push(`⚠️ ${contextLine}`);
      } else if (usagePercent > 50) {
        this.tokenCounterEl.classList.add('warning');
        lines.push(contextLine);
      } else {
        lines.push(contextLine);
      }
    } else {
      this.tokenCounterEl.classList.remove('warning', 'danger');
      lines.push('Context window size not reported for this model');
    }

    if (this.cumulativeCache.read > 0) {
      const readCost = this.cumulativeCache.readCostUsd > 0
        ? ` ($${this.cumulativeCache.readCostUsd.toFixed(4)})`
        : '';
      lines.push(
        `Cache read: ${this.cumulativeCache.read.toLocaleString()} tokens${readCost}`
      );
    }
    if (this.cumulativeCache.creation > 0) {
      const writeCost = this.cumulativeCache.writeCostUsd > 0
        ? ` ($${this.cumulativeCache.writeCostUsd.toFixed(4)})`
        : '';
      lines.push(
        `Cache write: ${this.cumulativeCache.creation.toLocaleString()} tokens${writeCost}`
      );
    }
    if (this.cumulativeCache.savingsUsd > 0) {
      lines.push(`Cache savings: $${this.cumulativeCache.savingsUsd.toFixed(4)}`);
    }
    if (this.cumulativeInputEstimated) {
      lines.push('Input tokens estimated — provider omitted exact prompt counts');
    }
    if (this.cumulativeUnknownCost) {
      lines.push('Cost unknown — subscription/compute-metered provider');
    } else if (this.cumulativeCost > 0) {
      lines.push(`Estimated cost: $${this.cumulativeCost.toFixed(4)}`);
    }
    if (['ollama_cloud_subscription', 'xai_oauth_subscription'].includes(this.tokenStatsMeta.billingMode)) {
      lines.push('Account quota: unavailable via API');
    }

    if (providerLabel) {
      lines.push(`Provider: ${providerLabel}`);
    }
    if (this.tokenStatsMeta.mode) {
      lines.push(`Mode: ${this.tokenStatsMeta.mode}`);
    }

    this.tokenCounterEl.title = lines.join('\n');
  }

  _renderContextUsageState() {
    this._renderTokenTooltip();
  }

  /**
   * Reset token counter (for new chat)
   */
  _resetTokenCounter() {
    this.cumulativeTokens = { input: 0, output: 0, total: 0 };
    this.cumulativeModelCalls = 0;
    this.modelCallCountComplete = true;
    this.currentContextTokens = 0;
    this.currentContextEstimated = false;
    this.cumulativeCost = 0;
    this.cumulativeCache = {
      read: 0,
      creation: 0,
      writeCostUsd: 0,
      readCostUsd: 0,
      savingsUsd: 0,
    };
    this.cumulativeUnknownCost = false;
    this.cumulativeInputEstimated = false;
    this.tokenStatsLocked = false;
    this.tokenStatsMeta = {
      provider: null,
      model: null,
      mode: null,
      billingMode: null,
      contextWindow: null,
    };
    
    if (this.tokenCounterEl) {
      this.tokenCounterEl.style.display = 'none';
      this.tokenCounterEl.classList.remove('warning', 'danger');
      this.tokenCounterEl.title = '';
    }
    if (this.tokenCountEl) {
      this.tokenCountEl.textContent = '0 tokens';
    }
    if (this.tokenCostEl) {
      this.tokenCostEl.textContent = '';
    }
  }

  async _resolveContextWindowForProviderModel(provider, modelId, mode = null) {
    const parseContextString = (value) => {
      if (!value) return null;
      if (typeof value === 'number') return value;
      const raw = String(value).trim().toUpperCase();
      const match = raw.match(/^(\d+(?:\.\d+)?)([KM]?)$/);
      if (!match) return null;
      const amount = parseFloat(match[1]);
      const suffix = match[2];
      if (suffix === 'M') return Math.round(amount * 1_000_000);
      if (suffix === 'K') return Math.round(amount * 1_000);
      return Math.round(amount);
    };

    try {
      const requestedMode = mode || this.socket?.mode || 'cloud';
      const res = await fetch(`/api/settings?mode=${encodeURIComponent(requestedMode)}`);
      if (!res.ok) return null;
      const data = await res.json();
      const settings = data.settings || {};
      const providerModels =
        settings.provider_models?.[provider]
        || settings.llm?.model?.options
        || [];
      const selectedModel = providerModels.find((entry) => entry.id === modelId);
      const selectedContext = parseContextString(selectedModel?.context);
      if (selectedContext) return selectedContext;

      if (provider === 'xai') return 1_000_000;
      if (provider === 'anthropic') return 1_000_000;
      if (provider === 'openai') return 128_000;
      if (provider === 'ollama' && modelId) {
        const ctxRes = await fetch(`/api/ollama/model-context?mode=${requestedMode}&model=${encodeURIComponent(modelId)}`);
        if (ctxRes.ok) {
          const ctxData = await ctxRes.json();
          if (ctxData.context_length) return parseInt(ctxData.context_length, 10);
        }
      }
    } catch (err) {
      console.warn('[Chat] Could not resolve context window for conversation:', err);
    }
    return null;
  }

  /**
   * Restore token counter from historical data (when loading a conversation)
   * @param {Object} tokens - {input, output, total}
   * @param {number} cost - cumulative cost in USD
   * @param {boolean} unknownCost - true for subscription/compute-metered providers
   * @param {boolean} inputEstimated - true when input tokens were approximated
   * @param {Object} meta - optional provider/model/mode, context and cache metadata
   */
  async restoreTokenCounter(tokens, cost, unknownCost = false, inputEstimated = false, meta = null) {
    if (!this.tokenCounterEl) return;
    
    this.cumulativeTokens = { ...tokens };
    this.cumulativeModelCalls = meta?.modelCalls || 0;
    this.modelCallCountComplete = meta?.modelCallsComplete !== false;
    this.currentContextTokens = meta?.currentContextTokens || 0;
    this.currentContextEstimated = meta?.currentContextEstimated === true;
    this.cumulativeCost = cost || 0;
    this.cumulativeCache = {
      read: meta?.cache?.read || 0,
      creation: meta?.cache?.creation || 0,
      writeCostUsd: meta?.cache?.writeCostUsd || 0,
      readCostUsd: meta?.cache?.readCostUsd || 0,
      savingsUsd: meta?.cache?.savingsUsd || 0,
    };
    this.cumulativeUnknownCost = unknownCost === true;
    this.cumulativeInputEstimated = inputEstimated === true;
    this.tokenStatsLocked = true;

    const provider = meta?.provider || null;
    const model = meta?.model || null;
    const mode = meta?.mode || null;
    const billingMode = meta?.billingMode || null;
    let contextWindow = meta?.contextWindow || null;
    const restoredMeta = { provider, model, mode, billingMode, contextWindow };
    this.tokenStatsMeta = restoredMeta;
    if (!contextWindow && provider) {
      contextWindow = await this._resolveContextWindowForProviderModel(provider, model, mode);
    }
    // A live response or another conversation can arrive during metadata lookup.
    if (this.tokenStatsMeta !== restoredMeta || restoredMeta.provider !== provider
        || restoredMeta.model !== model || restoredMeta.mode !== mode) return;
    this.tokenStatsMeta.contextWindow = contextWindow;

    this._renderTokenCount();
    this._renderCostLabel();
    this.tokenCounterEl.style.display = 'flex';
    this._renderTokenTooltip();
  }

  /**
   * Clear chat history
   */
  clearChat({ preserveAttachments = false, preservePreparation = false } = {}) {
    this._cancelRecording({ silent: true });
    this._renderedMessageIds = new Set();
    const clearedSources = !preserveAttachments && Boolean(
      this.attachedDocuments.length || this.attachedImages.length
      || this.pendingImageFiles?.length || this.pendingImageBatch?.length
      || this.pendingVisionRetryPayload?.images?.length
    );
    if (!preserveAttachments) {
      this._pendingSend = null;
      this.cancelAttachmentPreparation();
      this.clearAttachedFile();
      this.clearAttachedImage();
    }
    this._conversationLoadPending = false;
    if (!preservePreparation || !(this._attachmentSend || this._imageUpload)) this._resetProcessingUi();
    this.currentMessageId = null;
    this._resetPendingToolState();

    // Keep only the welcome message
    this.messagesContainer.querySelectorAll('video').forEach(video => video.pause?.());
    const messages = this.messagesContainer.querySelectorAll('.message');
    messages.forEach((msg, index) => {
      if (index > 0) msg.remove();
    });
    
    // Reset token counter for new chat
    this._resetTokenCounter();
    return clearedSources;
  }
}

// Create global instance
window.chatUI = new ChatUI();
