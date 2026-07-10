/**
 * Jarvis Web UI - Chat Interface
 */

/**
 * Workflow and Prompt System
 * Handles /workflows and @prompts for enhanced chat interaction
 */
class CommandSystem {
  constructor() {
    this.prompts = {};     // @prompt registry
    this.workflows = {};   // /workflow registry (multi-tool pipelines)
    this.tools = {};       // #tool hint registry
    this.maxToolHints = 5;
    this.loaded = false;
    this._loadRegistry();
  }

  /**
   * Load prompts and workflows from server
   */
  async _loadRegistry() {
    try {
      // Load prompts, workflows, and enabled tools in parallel
      const [promptsRes, workflowsRes, toolsRes] = await Promise.all([
        fetch('/api/prompts'),
        fetch('/api/workflows'),
        fetch('/api/tools?summary=true&include_blocked=false')
      ]);
      
      if (promptsRes.ok) {
        const data = await promptsRes.json();
        this.prompts = data.prompts || {};
      }
      
      if (workflowsRes.ok) {
        const data = await workflowsRes.json();
        this.workflows = data.workflows || {};
      }

      if (toolsRes.ok) {
        const data = await toolsRes.json();
        this._setToolsFromList(data.tools || []);
      }
      
      this.loaded = true;
      console.log('[Commands] Loaded:', Object.keys(this.prompts).length, 'prompts,',
                  Object.keys(this.workflows || {}).length, 'workflows,',
                  Object.keys(this.tools || {}).length, 'tools');
    } catch (err) {
      console.warn('[Commands] Failed to load registry:', err);
    }
  }

  _setToolsFromList(tools) {
    this.tools = {};
    for (const tool of tools || []) {
      if (!tool || !tool.name || tool.blocked || tool.enabled === false) continue;
      this.tools[tool.name] = tool;
    }
  }

  async refreshTools() {
    try {
      const [toolsRes, promptsRes] = await Promise.all([
        fetch('/api/tools?summary=true&include_blocked=false'),
        fetch('/api/prompts')
      ]);
      if (toolsRes.ok) {
        const data = await toolsRes.json();
        this._setToolsFromList(data.tools || []);
      }
      if (promptsRes.ok) {
        const data = await promptsRes.json();
        this.prompts = data.prompts || {};
      }
    } catch (err) {
      console.warn('[Commands] Failed to refresh tools/prompts:', err);
    }
  }

  _toolMatchesQuery(name, query) {
    if (!query) return true;
    const lowered = name.toLowerCase();
    const q = query.toLowerCase();
    return lowered.startsWith(q) || lowered.split(/[_-]/).some(part => part.startsWith(q));
  }

  getTool(name) {
    const tool = this.tools?.[name];
    if (!tool || tool.blocked || tool.enabled === false) return null;
    return tool;
  }

  getAmbientToolSuggestions(text, selectedNames = [], limit = 3) {
    const cleanText = (text || '').trim();
    if (cleanText.length < 8) return [];

    const selected = new Set(selectedNames || []);
    const stopwords = new Set([
      'about', 'after', 'again', 'also', 'and', 'are', 'can', 'could', 'for',
      'from', 'have', 'help', 'how', 'into', 'just', 'like', 'make', 'need',
      'please', 'show', 'that', 'the', 'this', 'use', 'want', 'what', 'when',
      'where', 'with', 'would', 'you'
    ]);
    const normalized = cleanText.toLowerCase();
    const tokens = [...new Set((normalized.match(/[a-z0-9]{3,}/g) || [])
      .filter(token => !stopwords.has(token)))];
    if (tokens.length === 0) return [];

    return Object.entries(this.tools || {})
      .filter(([name, tool]) => !selected.has(name) && tool && tool.enabled !== false && !tool.blocked)
      .map(([name, tool]) => {
        const nameLower = name.toLowerCase();
        const nameWords = nameLower.split(/[_-]+/).filter(Boolean);
        const description = (tool.description || '').toLowerCase();
        const source = (tool.source || '').toLowerCase();
        const haystack = `${nameWords.join(' ')} ${description} ${source}`;
        let score = 0;

        if (normalized.includes(nameLower)) score += 12;
        for (const word of nameWords) {
          if (word.length >= 3 && normalized.includes(word)) score += 4;
        }

        for (const token of tokens) {
          if (nameWords.some(word => word.startsWith(token) || token.startsWith(word))) {
            score += 4;
          } else if (description.includes(token)) {
            score += 2;
          } else if (haystack.includes(token)) {
            score += 1;
          }
        }

        return {
          type: 'tool',
          name,
          prefix: '#',
          icon: tool.source === 'mcp' ? '🔌' : '🛠️',
          description: tool.description || `Prefer ${name} for this request`,
          source: tool.source || 'local',
          score
        };
      })
      .filter(item => item.score >= 3)
      .sort((a, b) => b.score - a.score || a.name.localeCompare(b.name))
      .slice(0, limit);
  }
  
  /**
   * Get autocomplete suggestions for input
   * @param {string} input - Current input text
   * @returns {Array} Suggestions [{type, name, icon, description}]
   */
  getSuggestions(input) {
    const suggestions = [];

    // Check for /workflow prefix
    if (input.startsWith('/')) {
      const query = input.slice(1).toLowerCase();
      
      // Add workflow suggestions
      for (const [id, wf] of Object.entries(this.workflows || {})) {
        // Match against workflow triggers (e.g., /research, /note)
        const triggers = wf.triggers || [];
        for (const trigger of triggers) {
          if (!trigger.startsWith('/')) continue;
          const triggerName = trigger.replace('/', '');
          if (triggerName.toLowerCase().startsWith(query) || query === '') {
            suggestions.push({
              type: 'workflow',
              name: triggerName,
              prefix: '/',
              icon: wf.icon || '🔄',
              description: wf.description || `${wf.name} (${wf.step_count} steps)`,
              workflow_id: id,
              steps: wf.steps || [],  // Include steps for tooltip
              tools_used: wf.tools_used || []
            });
            break; // Only add once per workflow
          }
        }
      }
    }
    
    // Check for *bookmark search prefix (Firefox-style)
    if (input.startsWith('*')) {
      const query = input.slice(1).toLowerCase();
      for (const [id, wf] of Object.entries(this.workflows || {})) {
        const triggers = wf.triggers || [];
        for (const trigger of triggers) {
          if (trigger === '*' || trigger.startsWith('*')) {
            const triggerName = trigger.replace('*', '') || 'bookmarks';
            suggestions.push({
              type: 'workflow',
              name: wf.name || 'Search bookmarks',
              prefix: '*',
              icon: '🔖',
              description: wf.description || 'Search your Firefox bookmarks',
              workflow_id: id,
              steps: wf.steps || [],
              tools_used: wf.tools_used || []
            });
            break;
          }
        }
      }
    }
    
    // Check for @prompt prefix
    if (input.startsWith('@')) {
      const query = input.slice(1).toLowerCase();
      for (const [name, prompt] of Object.entries(this.prompts)) {
        if (name.toLowerCase().startsWith(query) || query === '') {
          suggestions.push({
            type: 'prompt',
            name: name,
            icon: '📝',
            description: prompt.description || `Use ${name} methodology`,
            key_points: prompt.key_points || []  // Include key points for tooltip
          });
        }
      }
    }

    // Check for #tool hint prefix
    if (input.startsWith('#')) {
      const query = input.slice(1).toLowerCase();
      for (const [name, tool] of Object.entries(this.tools || {})) {
        if (this._toolMatchesQuery(name, query)) {
          suggestions.push({
            type: 'tool',
            name: name,
            prefix: '#',
            icon: tool.source === 'mcp' ? '🔌' : '🛠️',
            description: tool.description || `Prefer ${name} for this request`,
            source: tool.source || 'local'
          });
        }
      }
    }
    
    const sorted = suggestions.sort((a, b) => a.name.localeCompare(b.name));
    // Tool hints are intentionally scrollable: the user should be able to browse
    // every currently enabled tool, while prompts/workflows stay compact.
    if (input.startsWith('#')) {
      return sorted;
    }
    return sorted.slice(0, 30);
  }
  
  /**
   * Parse input and extract workflow/prompt + message
   * @param {string} input - Raw input text
   * @returns {Object} {workflow?, prompt?, message, instruction?}
   */
  parseInput(input) {
    const result = {
      prompt: null,
      workflow: null,
      toolHints: [],
      message: input,
      instruction: null
    };
    
    // Check for *bookmark search (Firefox-style)
    if (input.startsWith('*')) {
      for (const [id, wf] of Object.entries(this.workflows || {})) {
        const triggers = wf.triggers || [];
        if (triggers.includes('*')) {
          result.workflow = id;
          result.message = input; // Keep full message for orchestrator's workflow detection
          return result;
        }
      }
    }
    
    // Check for /workflow
    const cmdMatch = input.match(/^\/(\w+[-\w]*)\s*(.*)/s);
    if (cmdMatch) {
      const cmdName = cmdMatch[1].toLowerCase();
      
      // Check if it's a workflow trigger
      for (const [id, wf] of Object.entries(this.workflows || {})) {
        const triggers = wf.triggers || [];
        for (const trigger of triggers) {
          if (trigger.startsWith('/') && trigger.replace('/', '') === cmdName) {
            result.workflow = id;
            result.message = input; // Keep full message for orchestrator's workflow detection
            return result; // Workflows don't combine with @prompts
          }
        }
      }
    }
    
    // Check for @prompt (only if not a workflow)
    const promptMatch = result.message.match(/^@(\w+)\s*(.*)/s);
    if (promptMatch) {
      const promptName = promptMatch[1].toLowerCase();
      const prompt = this.prompts[promptName];
      if (prompt) {
        result.prompt = promptName;
        result.message = promptMatch[2].trim();
        result.instruction = prompt.content || '';
        const promptHints = Array.isArray(prompt.tool_hints) ? prompt.tool_hints : [];
        for (const name of promptHints) {
          const tool = this.tools[name];
          if (!tool || tool.blocked || tool.enabled === false) continue;
          if (!result.toolHints.includes(name) && result.toolHints.length < this.maxToolHints) {
            result.toolHints.push(name);
          }
        }
      }
    }

    // Extract standalone #tool_name hints from the remaining message.
    // Unknown hashtags are left alone so normal prose is not accidentally removed.
    const hints = [];
    result.message = result.message.replace(/(^|\s)#([A-Za-z0-9_-]+)(?=\s|$)/g, (full, leading, name) => {
      const tool = this.tools[name];
      if (!tool || tool.blocked || tool.enabled === false) return full;
      if (!hints.includes(name) && hints.length < this.maxToolHints) {
        hints.push(name);
      }
      return leading;
    }).replace(/\s{2,}/g, ' ').trim();
    for (const name of hints) {
      if (!result.toolHints.includes(name) && result.toolHints.length < this.maxToolHints) {
        result.toolHints.push(name);
      }
    }

    return result;
  }
  
  /**
   * Get display text for active workflow/prompt
   */
  getActiveDisplay(parsed) {
    const parts = [];
    if (parsed.workflow) {
      const wf = this.workflows[parsed.workflow];
      const prefix = (wf?.triggers || []).includes('*') ? '*' : '/';
      parts.push(`${prefix}${parsed.workflow === 'bookmark_search' ? 'bookmarks' : parsed.workflow} ${wf?.icon || '🔄'}`);
    }
    if (parsed.prompt) {
      parts.push(`@${parsed.prompt} 📝`);
    }
    if (parsed.toolHints && parsed.toolHints.length > 0) {
      parts.push(parsed.toolHints.map(name => `#${name}`).join(' ') + ' 🛠️');
    }
    return parts.join(' + ');
  }

  /**
   * Rebuild prompt/tool provenance from a saved user message.
   * Historical badges describe what was selected for that turn, even if a
   * referenced prompt or tool is no longer available in the current mode.
   */
  getPersistedDisplay(data = {}) {
    const isSafeName = (value) => (
      typeof value === 'string' && /^[A-Za-z0-9_-]+$/.test(value)
    );
    const prompt = isSafeName(data?.prompt) ? data.prompt : null;
    const toolHints = [];
    for (const name of Array.isArray(data?.tool_hints) ? data.tool_hints : []) {
      if (!isSafeName(name) || toolHints.includes(name)) continue;
      toolHints.push(name);
      if (toolHints.length >= this.maxToolHints) break;
    }

    return this.getActiveDisplay({ prompt, workflow: null, toolHints });
  }
}

// Global command system instance
window.commandSystem = new CommandSystem();


class ChatUI {
  constructor() {
    this.messagesContainer = document.getElementById('chatMessages');
    this.inputField = document.getElementById('chatInput');
    this.sendBtn = document.getElementById('sendBtn');
    this.micBtn = document.getElementById('micBtn');
    this.enhanceBtn = document.getElementById('enhanceBtn');
    this.stopBtn = document.getElementById('stopBtn');
    
    // File upload elements (images + text files)
    this.uploadBtn = document.getElementById('uploadBtn');
    this.fileInput = document.getElementById('fileInput');
    this.imagePreviewContainer = document.getElementById('imagePreviewContainer');
    this.imagePreviewStrip = document.getElementById('imagePreviewStrip');
    this.imageActionBadge = document.getElementById('imageActionBadge');
    this.clearAllImagesBtn = document.getElementById('clearAllImagesBtn');
    
    // Text file preview elements
    this.filePreviewContainer = document.getElementById('filePreviewContainer');
    this.filePreviewName = document.getElementById('filePreviewName');
    this.filePreviewSize = document.getElementById('filePreviewSize');
    this.removeFileBtn = document.getElementById('removeFileBtn');
    
    // File conversion elements
    this.convertBtn = document.getElementById('convertBtn');
    this.convertInput = document.getElementById('convertInput');
    this.convertModal = document.getElementById('convertModal');
    this.convertTargetFormat = document.getElementById('convertTargetFormat');
    this.convertFileName = document.getElementById('convertFileName');
    this.convertPreview = document.getElementById('convertPreview');
    this.pendingConvertFile = null;  // {file, stashRef}
    
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
    
    this._setupEventListeners();
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
    // Send button
    this.sendBtn.addEventListener('click', () => this.sendMessage());
    
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

  _renderToolHintChips() {
    if (!this.toolHintsContainer) return;

    if (this.selectedToolHints.length === 0) {
      this.toolHintsContainer.innerHTML = '';
      this.toolHintsContainer.style.display = 'none';
      return;
    }

    const chips = this.selectedToolHints.map(name => `
      <span class="tool-hint-chip" title="Prefer ${this._escapeAttr(name)} for this request">
        <span class="tool-hint-name">#${Utils.escapeHtml(name)}</span>
        <button type="button" class="tool-hint-remove" data-tool="${this._escapeAttr(name)}" title="Remove #${this._escapeAttr(name)}">x</button>
      </span>
    `).join('');

    this.toolHintsContainer.innerHTML = `
      <span class="tool-hint-label">Tool hints</span>
      ${chips}
    `;
    this.toolHintsContainer.style.display = 'flex';

    this.toolHintsContainer.querySelectorAll('.tool-hint-remove').forEach(button => {
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
    const input = this.inputField.value.trim();
    
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
      return;
    }
    
    // Replace entire input with selected workflow/prompt + space
    // For * bookmarks: preserve query after * if user already typed it (e.g. *docker -> *docker )
    const currentVal = this.inputField.value;
    const afterStar = prefix === '*' && currentVal.startsWith('*') ? currentVal.slice(1).trim() : '';
    this.inputField.value = prefix === '*' ? `*${afterStar ? ' ' + afterStar : ''} ` : `${prefix}${name} `;
    
    this.inputField.focus();
    this._hideAutocomplete();
  }

  /**
   * Setup voice recording (click-to-toggle mode)
   * Click once to start recording, click again to stop and send
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
    
    // Keyboard support: Space to toggle recording
    this.micBtn.addEventListener('keydown', (e) => {
      if (e.code === 'Space') {
        e.preventDefault();
        if (this.isRecording) {
          this._stopRecording();
        } else {
          this._startRecording();
        }
      }
    });
    
    // Escape to cancel
    document.addEventListener('keydown', (e) => {
      if (e.code === 'Escape' && this.isRecording) {
        this._cancelRecording();
      }
    });
  }
  
  /**
   * Start voice recording with ready indicator
   */
  async _startRecording() {
    if (this.isRecording || this.isProcessing) return;
    
    // Show "preparing" state
    this.micBtn.classList.add('preparing');
    this.micBtn.title = 'Preparing...';
    
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
      
      // Create MediaRecorder
      const mimeType = this._getSupportedMimeType();
      this.mediaRecorder = new MediaRecorder(stream, { mimeType });
      this.audioChunks = [];
      this._recordingStream = stream; // Store for cleanup
      
      this.mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) {
          this.audioChunks.push(e.data);
        }
      };
      
      this.mediaRecorder.onstop = () => {
        // Stop all tracks
        if (this._recordingStream) {
          this._recordingStream.getTracks().forEach(track => track.stop());
          this._recordingStream = null;
        }
        
        // Process the recording
        this._processRecording();
      };
      
      // Brief delay to let user see "ready" state before recording
      this.micBtn.classList.remove('preparing');
      this.micBtn.classList.add('ready');
      this.micBtn.title = 'Listening... Click again when done';
      
      // Show toast with instruction
      Utils.toast('🎤 Listening... Click mic again when done', 'info', 3000);
      
      // Small delay so user knows to start speaking
      await new Promise(resolve => setTimeout(resolve, 300));
      
      // Start recording
      this.mediaRecorder.start(100); // Collect data every 100ms
      this.isRecording = true;
      
      // Update UI to recording state
      this.micBtn.classList.remove('ready');
      this.micBtn.classList.add('recording');
      this._showRecordingIndicator();
      
      console.log('[Chat] Recording started');
      
    } catch (err) {
      console.error('[Chat] Failed to start recording:', err);
      this.micBtn.classList.remove('preparing', 'ready');
      
      if (err.name === 'NotAllowedError') {
        Utils.toast('Microphone access denied. Click the lock icon in your browser address bar to allow.', 'error', 5000);
      } else if (err.name === 'NotFoundError') {
        Utils.toast('No microphone found', 'error');
      } else {
        Utils.toast('Failed to start recording: ' + err.message, 'error');
      }
      
      this.micBtn.title = 'Click to record';
    }
  }
  
  /**
   * Stop voice recording
   */
  _stopRecording() {
    if (!this.isRecording || !this.mediaRecorder) return;
    
    console.log('[Chat] Stopping recording...');
    this.isRecording = false;
    this.mediaRecorder.stop();
    
    // Update UI
    this.micBtn.classList.remove('recording', 'ready');
    this.micBtn.classList.add('processing');
    this.micBtn.title = 'Transcribing...';
    this._hideRecordingIndicator();
  }
  
  /**
   * Cancel recording without sending
   */
  _cancelRecording() {
    if (!this.isRecording) return;
    
    console.log('[Chat] Recording cancelled');
    this.isRecording = false;
    this.audioChunks = [];
    
    // Stop stream directly
    if (this._recordingStream) {
      this._recordingStream.getTracks().forEach(track => track.stop());
      this._recordingStream = null;
    }
    
    // Stop recorder without processing
    if (this.mediaRecorder && this.mediaRecorder.state !== 'inactive') {
      this.mediaRecorder.onstop = () => {}; // Clear handler
      this.mediaRecorder.stop();
    }
    
    // Update UI
    this.micBtn.classList.remove('recording', 'ready', 'preparing');
    this.micBtn.title = 'Click to record';
    this._hideRecordingIndicator();
    
    Utils.toast('Recording cancelled (Esc)', 'info');
  }
  
  /**
   * Process recorded audio - send to STT API
   */
  async _processRecording() {
    this._hideRecordingIndicator();
    
    if (this.audioChunks.length === 0) {
      console.log('[Chat] No audio recorded');
      this._resetMicButton();
      return;
    }
    
    const audioBlob = new Blob(this.audioChunks, { type: this._getSupportedMimeType() });
    console.log('[Chat] Audio blob size:', audioBlob.size, 'type:', audioBlob.type);
    
    // Check minimum size (very short recordings won't have speech)
    if (audioBlob.size < 5000) {
      console.log('[Chat] Recording too short');
      Utils.toast('Recording too short - speak longer before clicking again', 'warning');
      this._resetMicButton();
      return;
    }
    
    try {
      // Send to STT API
      const formData = new FormData();
      formData.append('audio', audioBlob, 'recording.webm');
      formData.append('mode', window.jarvisSocket?.mode || 'cloud');
      
      console.log('[Chat] Sending audio for transcription...');
      
      const response = await fetch('/api/stt', {
        method: 'POST',
        body: formData
      });
      
      const data = await response.json();
      
      if (data.ok && data.text) {
        console.log('[Chat] Transcribed:', data.text);
        
        // Put text in input field
        this.inputField.value = data.text;
        Utils.autoResize(this.inputField);
        
        // Auto-send the message
        this.sendMessage();
        
        Utils.toast('🎤 ' + Utils.truncate(data.text, 30), 'success', 2000);
      } else {
        console.warn('[Chat] STT failed:', data.error);
        Utils.toast(data.error || 'Speech recognition failed', 'error');
      }
      
    } catch (err) {
      console.error('[Chat] STT error:', err);
      Utils.toast('Failed to process audio: ' + err.message, 'error');
    } finally {
      this._resetMicButton();
    }
  }
  
  /**
   * Reset mic button to default state
   */
  _resetMicButton() {
    this.micBtn.classList.remove('recording', 'processing', 'ready', 'preparing');
    this.micBtn.title = 'Click to record';
    this.audioChunks = [];
    this.mediaRecorder = null;
    this._recordingStream = null;
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
      this.currentMessageId = data.message_id;
      this._activatePendingToolsForMessage(data.message_id, true);
      this.isProcessing = true;
      this.updateSendButton();
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
        // Update specific tool card with progress
        this.updateToolCard(data.tool, 'pending', { progress: data.progress, status: data.status });
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
      this.updateToolCard(cardId, data.tool, 'success', data.result, data.duration_ms);
    });
    
    socket.on('toolError', (data) => {
      this._activatePendingToolsForMessage(data.message_id);
      this._markToolFinished(data);
      // Use call_index for unique card ID when same tool called multiple times
      const cardId = data.call_index > 0 ? `${data.tool}_${data.call_index}` : data.tool;
      this.updateToolCard(cardId, data.tool, 'error', { error: data.error });
    });

    socket.on('modeChanged', (data) => {
      this._handleImageAttachmentsForMode(data.mode);
    });
    
    socket.on('response', (data) => {
      this._activatePendingToolsForMessage(data.message_id);
      this.hideThinking();
      this.clearStatus();  // Clear any status messages
      this.pendingVisionRetryPayload = null;
      this.addAssistantMessage(data.text, data.tools_used, data);
      this.currentMessageId = null;
      this.isProcessing = false;
      this.updateSendButton();
      
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
      this._clearPendingToolsForMessage(data.message_id);
      if (
        ['vision_model_unsupported', 'vision_analysis_failed', 'image_edit_stash_failed'].includes(data.error_code)
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
      if (!data?.message_id || !this.currentMessageId || this.currentMessageId === data.message_id) {
        this._resetProcessingUi();
        this.currentMessageId = null;
      }

      Utils.toast('Stopping current task...', 'info', 1500);
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
      this._handleCompletionGuardTerminalUi(data);
      this._updateCompletionGuardCard(data);
    });

    socket.on('completionGuardTicketCreated', (data) => {
      this._handleCompletionGuardTerminalUi({
        ...data,
        status: 'ticket_created'
      });
      this._updateCompletionGuardCard({
        ...data,
        status: 'ticket_created'
      });
      Utils.toast('Completion issue logged for follow-up', 'warning', 4000);
    });

    socket.on('completionGuardError', (data) => {
      const staleContext = /expired|not found|missing_session_context/i.test(data?.error || '');
      this._handleCompletionGuardTerminalUi({
        ...data,
        status: staleContext ? 'expired' : 'error'
      });
      this._updateCompletionGuardCard({
        ...data,
        status: staleContext ? 'expired' : 'error'
      });
      if (!staleContext) {
        Utils.toast(data.error || 'Completion Guard failed', 'error', 4000);
      }
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
    
    // Attached text file state
    this.attachedFile = null;
    
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
    
    // Remove text file button
    if (this.removeFileBtn) {
      this.removeFileBtn.addEventListener('click', () => {
        this.clearAttachedFile();
      });
    }
    
    // Drag and drop support (images + text files)
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
      imageProviderSelect.addEventListener('change', () => this._updateImageProviderOptions());
    }

    const videoProviderSelect = document.getElementById('imgActionVideoProvider');
    if (videoProviderSelect) {
      videoProviderSelect.addEventListener('change', () => this._updateVideoProviderOptions());
    }
    
    console.log('[Chat] Image action modal ready');
  }
  
  /**
   * Show the image action modal with preview
   */
  async _showImageActionModal(uploadDataOrArray) {
    if (!this.imageActionModal) return;

    try {
      await window.jarvisApp?._ensureSettingsData?.(window.jarvisSocket?.mode || 'cloud');
    } catch (error) {
      console.warn('[Chat] Could not refresh media model settings:', error);
    }
    
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
    
    // Reset to default (Analyze)
    const analyzeRadio = this.imageActionModal.querySelector('input[name="imageAction"][value="analyze"]');
    if (analyzeRadio) analyzeRadio.checked = true;
    
    // Reset options visibility
    this._updateImageActionOptions();
    this._resetImageActionOptions();
    
    // Show modal
    this.imageActionModal.classList.add('active');
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
   * Show/hide provider-specific options for Image to Image
   */
  _updateImageProviderOptions() {
    const provider = document.getElementById('imgActionImageProvider')?.value || 'gemini';
    
    const geminiOpts = document.getElementById('imgActionGeminiOpts');
    const openaiOpts = document.getElementById('imgActionOpenaiOpts');
    const xaiOpts = document.getElementById('imgActionXaiOpts');
    
    if (geminiOpts) geminiOpts.style.display = provider === 'gemini' ? 'block' : 'none';
    if (openaiOpts) openaiOpts.style.display = provider === 'openai' ? 'block' : 'none';
    if (xaiOpts) xaiOpts.style.display = provider === 'xai' ? 'block' : 'none';

    const providerMetadata = window.jarvisApp?._settingsData?.image_providers?.[provider];
    const openaiMetadata = window.jarvisApp?._settingsData?.image_providers?.openai;
    const openaiModel = openaiMetadata?.model || 'gpt-image-2';
    const openaiCapabilities = Array.isArray(openaiMetadata?.capabilities)
      ? openaiMetadata.capabilities
      : [];
    const transparent = document.getElementById('imgActionTransparent');
    const transparentDesc = document.getElementById('imgActionTransparentDesc');
    const modelDesc = document.getElementById('imgActionImageModelDesc');
    const supportsTransparent = openaiCapabilities.includes('transparent_background')
      || (openaiCapabilities.length === 0 && !String(openaiModel).startsWith('gpt-image-2'));
    if (modelDesc) {
      const effectiveModel = providerMetadata?.model_name || providerMetadata?.model;
      modelDesc.textContent = effectiveModel ? `Effective model: ${effectiveModel}` : '';
    }
    if (transparent) {
      transparent.disabled = provider === 'openai' && !supportsTransparent;
      if (transparent.disabled) transparent.checked = false;
    }
    if (transparentDesc) {
      transparentDesc.textContent = supportsTransparent
        ? 'For logos, sprites, overlays (png/webp)'
        : `${openaiModel} does not support transparent backgrounds`;
    }
  }

  /**
   * Populate video resolutions from the effective model in the shared catalog.
   */
  _updateVideoProviderOptions() {
    const provider = document.getElementById('imgActionVideoProvider')?.value || 'xai';
    const select = document.getElementById('imgActionVideoResolution');
    const resolutions = window.jarvisApp?._settingsData?.video_providers?.[provider]?.resolutions;
    if (!select || !Array.isArray(resolutions) || resolutions.length === 0) return;

    const previous = select.value;
    select.innerHTML = '';
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
    if (select?.value && ['xai', 'openai', 'gemini'].includes(select.value)) {
      return select.value;
    }
    const value = window.jarvisApp?._settingsData?.video?.provider?.value;
    return ['xai', 'openai', 'gemini'].includes(value) ? value : 'xai';
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
    this._updateVideoProviderOptions();
    this._applyMediaProviderAvailability(videoProvider, 'video');
    if (videoResolution && [...videoResolution.options].some(option => option.value === '720p')) {
      videoResolution.value = '720p';
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
    this._updateImageProviderOptions();
  }
  
  /**
   * Collect settings from the image action modal based on selected action
   */
  _collectImageActionSettings() {
    const action = this.imageActionModal?.querySelector('input[name="imageAction"]:checked')?.value || 'analyze';
    const settings = {};
    
    if (action === 'video') {
      settings.aspect_ratio = document.getElementById('imgActionVideoRatio')?.value || '16:9';
      settings.duration = parseInt(document.getElementById('imgActionVideoDuration')?.value) || 5;
      settings.resolution = document.getElementById('imgActionVideoResolution')?.value || '720p';
      settings.provider = document.getElementById('imgActionVideoProvider')?.value || 'xai';
    } else if (action === 'image') {
      const provider = document.getElementById('imgActionImageProvider')?.value || 'gemini';
      settings.provider = provider;
      
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
    if (!this.pendingImageBatch?.length) return;
    
    const { action, settings } = this._collectImageActionSettings();
    let batch = this.pendingImageBatch;
    
    if (action === 'video' || action === 'image') {
      if (batch.length > 1) {
        Utils.toast('Using first image for Video/Image mode', 'info', 2000);
      }
      batch = [batch[0]];
      this.attachedImages = [];
    }
    
    this.imageAttachmentAction = action;
    this.imageAttachmentSettings = settings;
    
    batch.forEach((uploadData) => {
      this.attachedImages.push({
        url: uploadData.url,
        filename: uploadData.filename
      });
    });

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

    if (!this.attachedImages.length) {
      container.style.display = 'none';
      if (this.imageActionBadge) {
        this.imageActionBadge.textContent = '';
      }
      return;
    }

    container.style.display = 'block';

    this.attachedImages.forEach((img, index) => {
      const thumb = document.createElement('div');
      thumb.className = 'image-preview-thumb';

      const imageEl = document.createElement('img');
      imageEl.src = img.url;
      imageEl.alt = `Preview ${index + 1}`;
      thumb.appendChild(imageEl);

      const removeBtn = document.createElement('button');
      removeBtn.type = 'button';
      removeBtn.className = 'remove-image-btn';
      removeBtn.title = 'Remove image';
      removeBtn.textContent = '×';
      removeBtn.addEventListener('click', () => this._removeAttachedImageAt(index));
      thumb.appendChild(removeBtn);

      strip.appendChild(thumb);
    });

    if (this.imageActionBadge) {
      const badgeText = this._buildActionBadgeText(this.imageAttachmentAction, this.imageAttachmentSettings);
      const countSuffix = this.attachedImages.length > 1 ? ` (${this.attachedImages.length})` : '';
      this.imageActionBadge.textContent = `${badgeText}${countSuffix}`;
    }
  }

  _removeAttachedImageAt(index) {
    if (index < 0 || index >= this.attachedImages.length) return;
    this.attachedImages.splice(index, 1);
    if (!this.attachedImages.length) {
      this.imageAttachmentAction = 'analyze';
      this.imageAttachmentSettings = {};
    }
    this._renderImagePreviews();
  }

  _handleImageAttachmentsForMode(mode, options = {}) {
    if (!this._hasAttachedImages() || this.imageAttachmentAction !== 'analyze') return;
    const maxImages = mode === 'local' ? 2 : 6;
    if (this.attachedImages.length <= maxImages) return;

    this.attachedImages = this.attachedImages.slice(0, maxImages);
    this._renderImagePreviews();
    if (options.toast !== false) {
      Utils.toast(`Kept first ${maxImages} image(s) for ${mode} mode`, 'info', 2500);
    }
  }
  
  async _uploadImageFiles(files) {
    const imageFiles = files.filter((file) => file.type.startsWith('image/'));
    if (!imageFiles.length) return [];

    const formData = new FormData();
    imageFiles.forEach((file) => formData.append('images', file));
    formData.append('mode', window.jarvisSocket?.mode || 'cloud');
    formData.append('include_base64', 'false');
    formData.append('current_image_count', String(this.attachedImages.length));

    try {
      const response = await fetch('/api/upload-images', {
        method: 'POST',
        body: formData
      });
      const data = await response.json();
      if (data.ok && Array.isArray(data.images) && data.images.length) {
        if (data.errors?.length) {
          Utils.toast(data.errors[0], 'warning', 2500);
        }
        return data.images;
      }
      if (data.error) {
        Utils.toast(data.error, 'error');
        return [];
      }
    } catch (err) {
      console.warn('[Chat] Batch upload failed, falling back to single uploads:', err);
    }

    const uploaded = [];
    for (const file of imageFiles) {
      const singleForm = new FormData();
      singleForm.append('image', file);
      singleForm.append('mode', window.jarvisSocket?.mode || 'cloud');
      singleForm.append('include_base64', 'false');
      singleForm.append('current_image_count', String(this.attachedImages.length + uploaded.length));
      const response = await fetch('/api/upload-image', {
        method: 'POST',
        body: singleForm
      });
      const data = await response.json();
      if (data.ok) {
        uploaded.push(data);
      } else if (data.error) {
        Utils.toast(data.error, 'error');
      }
    }
    return uploaded;
  }

  _appendAnalyzeImages(uploadResults) {
    uploadResults.forEach((uploadData) => {
      this.attachedImages.push({
        url: uploadData.url,
        filename: uploadData.filename
      });
    });
    this.imageAttachmentAction = 'analyze';
    this.imageAttachmentSettings = {};
    this._renderImagePreviews();
  }

  async attachImageFiles(files) {
    const imageFiles = Array.from(files).filter((file) => file.type.startsWith('image/'));
    if (!imageFiles.length) {
      Utils.toast('Please select image files', 'error');
      return;
    }

    this.clearAttachedFile();

    if (this._hasAttachedImages() && this.imageAttachmentAction !== 'analyze') {
      Utils.toast('Video/Image mode allows one reference image only', 'error');
      return;
    }

    const maxTotal = this._getMaxImages();
    const slots = maxTotal - this.attachedImages.length;
    if (slots <= 0) {
      Utils.toast(`Maximum ${maxTotal} images (${window.jarvisSocket?.mode === 'local' ? 'local' : 'cloud'} mode)`, 'error');
      return;
    }

    const toUpload = imageFiles.slice(0, slots);
    if (imageFiles.length > slots) {
      Utils.toast(`Only ${slots} more image(s) allowed (max ${maxTotal})`, 'info', 2500);
    }

    for (const file of toUpload) {
      if (file.size > 30 * 1024 * 1024) {
        Utils.toast(`${file.name} too large (max 30MB)`, 'error');
        return;
      }
    }

    try {
      Utils.toast(`Uploading ${toUpload.length} image(s)...`, 'info', 1500);
      const uploads = await this._uploadImageFiles(toUpload);
      if (!uploads.length) {
        Utils.toast('Failed to upload images', 'error');
        return;
      }

      if (this._canAppendWithoutModal()) {
        this._appendAnalyzeImages(uploads);
        Utils.toast(`Added ${uploads.length} image(s)`, 'success', 1500);
        this.inputField.focus();
        return;
      }

      await this._showImageActionModal(uploads);
    } catch (err) {
      console.error('[Chat] Image upload error:', err);
      Utils.toast('Failed to upload image', 'error');
    }
  }

  async _attachMultipleFiles(files) {
    const imageFiles = files.filter((file) => file.type.startsWith('image/'));
    const textFiles = files.filter((file) => {
      const ext = file.name.split('.').pop().toLowerCase();
      return ext === 'md' || ext === 'txt' || file.type === 'text/plain' || file.type === 'text/markdown';
    });

    if (imageFiles.length && !textFiles.length) {
      await this.attachImageFiles(imageFiles);
      return;
    }

    if (files.length === 1) {
      await this.attachFile(files[0]);
      return;
    }

    Utils.toast('Select either images or a single text file', 'error');
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
    this.convertPreview.innerHTML = '';
    if (file.type.startsWith('image/')) {
      const img = document.createElement('img');
      img.src = URL.createObjectURL(file);
      img.style.maxWidth = '200px';
      img.style.maxHeight = '150px';
      img.style.borderRadius = 'var(--radius-md)';
      this.convertPreview.appendChild(img);
      
      // Pre-select appropriate format based on current
      this._preselectFormat(file.name, 'image');
    } else if (file.type.startsWith('video/')) {
      const video = document.createElement('video');
      video.src = URL.createObjectURL(file);
      video.style.maxWidth = '200px';
      video.style.maxHeight = '150px';
      video.style.borderRadius = 'var(--radius-md)';
      video.controls = true;
      this.convertPreview.appendChild(video);
      
      this._preselectFormat(file.name, 'video');
    } else if (file.type.startsWith('audio/')) {
      const audio = document.createElement('audio');
      audio.src = URL.createObjectURL(file);
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
      this.sendMessage();
      
    } catch (err) {
      console.error('[Chat] Conversion error:', err);
      Utils.toast('Failed to start conversion: ' + err.message, 'error');
    }
  }
  
  /**
   * Route file attachment by type (images vs text files)
   */
  async attachFile(file) {
    if (!file) return;
    
    const ext = file.name.split('.').pop().toLowerCase();
    const isText = ext === 'md' || ext === 'txt' || file.type === 'text/plain' || file.type === 'text/markdown';
    
    if (file.type.startsWith('image/')) {
      await this.attachImage(file);
    } else if (isText) {
      await this.attachTextFile(file);
    } else {
      Utils.toast('Unsupported file type. Use images, .md, or .txt files.', 'error');
    }
  }
  
  /**
   * Attach a text file (.md, .txt) — read in browser, no server upload
   */
  async attachTextFile(file) {
    // Validate size (100KB max — ~25K tokens)
    if (file.size > 100 * 1024) {
      Utils.toast('Text file too large (max 100KB)', 'error');
      return;
    }
    
    try {
      const content = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = () => reject(reader.error);
        reader.readAsText(file);
      });
      
      // Clear any existing image attachment
      this.clearAttachedImage();
      
      // Store text file data
      this.attachedFile = {
        name: file.name,
        size: file.size,
        content: content,
        type: 'text'
      };
      
      // Show text file preview
      this._showFilePreview(file.name, file.size);
      
      Utils.toast(`Attached ${file.name}`, 'info', 1500);
      console.log(`[Chat] Text file attached: ${file.name} (${file.size} bytes)`);
      
    } catch (err) {
      console.error('[Chat] Text file read error:', err);
      Utils.toast('Failed to read text file', 'error');
    }
  }
  
  /**
   * Show text file preview indicator
   */
  _showFilePreview(name, size) {
    if (this.filePreviewContainer && this.filePreviewName && this.filePreviewSize) {
      this.filePreviewName.textContent = name;
      const sizeKb = (size / 1024).toFixed(1);
      this.filePreviewSize.textContent = `(${sizeKb} KB)`;
      this.filePreviewContainer.style.display = 'block';
    }
  }
  
  /**
   * Clear attached text file
   */
  clearAttachedFile() {
    this.attachedFile = null;
    if (this.filePreviewContainer) {
      this.filePreviewContainer.style.display = 'none';
    }
    if (this.filePreviewName) {
      this.filePreviewName.textContent = '';
    }
    if (this.filePreviewSize) {
      this.filePreviewSize.textContent = '';
    }
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
    this.attachedImages = [];
    this.imageAttachmentAction = 'analyze';
    this.imageAttachmentSettings = {};
    if (!options.preserveVisionRetry) {
      this.pendingVisionRetryPayload = null;
    }
    this._renderImagePreviews();
  }

  /**
   * Send a message (with optional attached image(s) or text file)
   */
  sendMessage() {
    let rawMessage = this.inputField.value.trim();
    const hasImage = this._hasAttachedImages();
    const imagePayload = this._getImageAttachmentPayload();
    const hasFile = this.attachedFile !== null;
    const hasSelectedToolHints = this.selectedToolHints.length > 0;
    
    // Need either message, image, or file
    if (!rawMessage && !hasImage && !hasFile && !hasSelectedToolHints) return;
    if (this.isProcessing) return;
    
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
    const toolHints = this._combineToolHints(parsed.toolHints || []);
    if (!parsed.message && toolHints.length > 0 && !hasImage && !hasFile) {
      Utils.toast('Add a task after the tool hint', 'info');
      return;
    }
    
    // Build display message (show original with decorations, show feedback badge if enabled)
    // The active badge already shows @prompt and recognized #tool selectors.
    // Keep the bubble focused on the user's task instead of displaying those
    // selectors twice. Workflows retain their original trigger text because
    // parseInput intentionally keeps it in parsed.message.
    const hasParsedSelectors = Boolean(parsed.prompt) || (parsed.toolHints || []).length > 0;
    let displayMessage = hasParsedSelectors
      ? parsed.message
      : this.inputField.value.trim();
    let activeBadge = '';
    const displayParsed = {
      ...parsed,
      toolHints
    };
    if (displayParsed.workflow || displayParsed.prompt || toolHints.length > 0) {
      activeBadge = window.commandSystem.getActiveDisplay(displayParsed);
    }
    if (requestFeedback) {
      activeBadge += (activeBadge ? ' ' : '') + '<span class="badge badge-feedback">📊</span>';
    }
    
    // Add file attachment indicator to display if text file attached
    if (hasFile) {
      const fileLabel = `📄 ${this.attachedFile.name}`;
      displayMessage = displayMessage ? `${fileLabel}\n${displayMessage}` : fileLabel;
    }
    
    // Add user message to UI (with image(s) if attached)
    this.addUserMessage(displayMessage, imagePayload, activeBadge);
    
    // Clear input
    this.inputField.value = '';
    this.selectedToolHints = [];
    this._renderToolHintChips();
    this._hideAmbientToolSuggestions();
    Utils.autoResize(this.inputField);
    
    // Send via socket (include image data, prompt metadata, and feedback request)
    this.isProcessing = true;
    this.updateSendButton();
    this._resetPendingToolState();
    this.pendingVisionRetryPayload = ['analyze', 'image'].includes(imagePayload?.action)
      ? {
          action: imagePayload.action,
          settings: { ...(imagePayload.settings || {}) },
          images: imagePayload.images.map(({ url, filename }) => ({ url, filename }))
        }
      : null;
    
    // Pass parsed data to socket (workflows are handled by orchestrator via /trigger)
    window.jarvisSocket.sendMessage(parsed.message, imagePayload, {
      system_instruction: parsed.instruction,
      prompt_name: parsed.prompt,
      tool_hints: toolHints
    }, requestFeedback, this.attachedFile);
    
    // Clear attachments after sending
    this.clearAttachedImage({ preserveVisionRetry: true });
    this.clearAttachedFile();
  }

  /**
   * Add user message to chat (with optional image(s) and active badge)
   */
  addUserMessage(text, imageData = null, activeBadge = '') {
    const messageEl = document.createElement('div');
    messageEl.className = 'message user';
    
    const images = this._normalizeMessageImages(imageData);
    let imageHtml = '';
    if (images.length === 1) {
      imageHtml = `
        <div class="message-image" onclick="window.showImageLightbox('${images[0].url}')">
          <img src="${images[0].url}" alt="Attached image" loading="lazy">
          <div class="image-overlay">
            <span>🔍 Click to expand</span>
          </div>
        </div>`;
    } else if (images.length > 1) {
      imageHtml = `<div class="message-images">${images.map((img, index) => `
        <div class="message-image" onclick="window.showImageLightbox('${img.url}')">
          <img src="${img.url}" alt="Attached image ${index + 1}" loading="lazy">
          <div class="image-overlay">
            <span>🔍 ${index + 1}/${images.length}</span>
          </div>
        </div>`).join('')}</div>`;
    }
    
    let badgeHtml = '';
    if (activeBadge) {
      // Don't escape - activeBadge may contain valid HTML (like feedback badge)
      badgeHtml = `<div class="command-badge">${activeBadge}</div>`;
    }
    
    const defaultPrompt = images.length > 1 ? '<em>What\'s in these images?</em>' : '<em>What\'s in this image?</em>';

    messageEl.innerHTML = `
      <div class="message-bubble">
        ${badgeHtml}
        ${imageHtml}
        ${text ? Utils.escapeHtml(text) : defaultPrompt}
      </div>
    `;
    
    this.messagesContainer.appendChild(messageEl);
    Utils.scrollToBottom(this.messagesContainer);
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
  addAssistantMessage(text, toolsUsed = [], data = {}) {
    // Safety: ensure text is a string
    if (typeof text === 'object' && text !== null) {
      // Handle case where object was passed instead of string
      const obj = text;
      text = obj.text || obj.content || obj.speech || '';
      toolsUsed = obj.tools_used || obj.toolsUsed || toolsUsed || [];
      data = obj.data || data || {};
    }
    text = text || '';

    // Only the latest Jarvis response can be sent to Canvas. This keeps the
    // action unambiguous and also works while conversation history is rebuilt.
    this.messagesContainer.querySelectorAll('.send-to-canvas-actions').forEach(actions => {
      actions.remove();
    });
    
    const messageEl = document.createElement('div');
    messageEl.className = 'message assistant new-message';
    const liveMessageId = data.message_id || data._web_message_id || data.data?._web_message_id || '';
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
    
    // Build tool cards HTML from pendingTools (supports duplicate tools with unique keys)
    let toolResultsData = data.data || data || {};
    toolResultsData = this._flattenWorkflowToolResults(toolResultsData);
    let toolCardsHtml = '';
    const toolTraceEntries = this._getToolTraceEntries(toolResultsData);
    this._reconcilePendingToolsWithFinalList(toolsUsed, toolTraceEntries);
    const pendingToolEntries = Object.entries(this.pendingTools);
    if (pendingToolEntries.length > 0) {
      toolCardsHtml = '<div class="tool-cards">';
      for (const entry of this._getPendingToolCardEntries(toolResultsData, pendingToolEntries)) {
        toolCardsHtml += this._createToolCardHtml(
          entry.displayName,
          entry.status,
          entry.result,
          entry.duration
        );
      }
      toolCardsHtml += '</div>';
    } else if (toolTraceEntries.length > 0) {
      toolCardsHtml = '<div class="tool-cards">';
      const toolOccurrenceCounts = {};
      const successfulToolOccurrenceCounts = {};
      for (const entry of toolTraceEntries) {
        const tool = entry.tool;
        const occurrenceIndex = toolOccurrenceCounts[tool] || 0;
        toolOccurrenceCounts[tool] = occurrenceIndex + 1;
        const status = entry.ok === false ? 'error' : 'success';
        const resultOccurrenceIndex = successfulToolOccurrenceCounts[tool] || 0;
        if (status === 'success') {
          successfulToolOccurrenceCounts[tool] = resultOccurrenceIndex + 1;
        }
        const fallback = status === 'error'
          ? this._getToolTraceFailureResult(entry)
          : this._getToolTraceSuccessFallback(entry);
        const toolResult = status === 'error'
          ? fallback
          : this._getToolResultForOccurrence(
            toolResultsData,
            tool,
            resultOccurrenceIndex,
            fallback
          );
        toolCardsHtml += this._createToolCardHtml(
          tool,
          status,
          toolResult,
          entry.duration_ms ?? null
        );
      }
      toolCardsHtml += '</div>';
    } else if (toolsUsed.length > 0) {
      // Fallback for non-workflow responses
      toolCardsHtml = '<div class="tool-cards">';
      const toolOccurrenceCounts = {};
      for (const tool of toolsUsed) {
        const occurrenceIndex = toolOccurrenceCounts[tool] || 0;
        toolOccurrenceCounts[tool] = occurrenceIndex + 1;
        const toolResult = this._getToolResultForOccurrence(toolResultsData, tool, occurrenceIndex);
        toolCardsHtml += this._createToolCardHtml(tool, 'success', toolResult, null);
      }
      toolCardsHtml += '</div>';
    }
    
    // Check for generated images
    let imageHtml = '';
    let filename = null;
    let shoppingHtml = '';
    
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
      Object.keys(this.pendingTools).some(k => k.startsWith('generate_image'));
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
    // Modular: no hardcoded tool names - any tool with stash_ref + image indicator displays
    // Skip tools that have their own display blocks (convert_file, generate_image)
    const toolsWithOwnImageDisplay = ['convert_file', 'generate_image'];
    if (!imageHtml) {
      const imageExtensions = /\.(png|jpg|jpeg|gif|webp|bmp|ico|tiff?|svg)$/i;
      for (const [toolName, toolResult] of Object.entries(toolResultsData)) {
        if (toolsWithOwnImageDisplay.includes(toolName)) continue;
        if (!toolResult || typeof toolResult !== 'object') continue;
        if (this._shouldSkipAssistantInlineImage(toolResult)) continue;
        const ref = toolResult.stash_ref || toolResult.ref;
        if (!ref) continue;
        const fn = toolResult.filename || toolResult.name || '';
        const mime = (toolResult.mime_type || '').toLowerCase();
        const isImage = imageExtensions.test(fn) || mime.startsWith('image/');
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
    
    // Method 1: Check data.generate_music object
    const musicData = data.generate_music;
    if (musicData && typeof musicData === 'object') {
      // Try various paths for audio URL
      audioUrl = musicData.audio_url
        || musicData.data?.audio_url
        || musicData.file_url;
      
      // If we have a stash reference, convert to API URL
      if (!audioUrl && musicData.stash_ref) {
        const stashMatch = musicData.stash_ref.match(/stash:\/\/([^/]+)\/(.+)/);
        if (stashMatch) {
          audioUrl = `/api/stash/${stashMatch[1]}/${stashMatch[2]}`;
        }
      }
      
      // Or get the filename from file_path
      if (!audioUrl && musicData.file_path) {
        const musicFilename = musicData.file_path.split('/').pop();
        audioUrl = `/api/music/${musicFilename}`;
      }
      
      // Get title
      audioTitle = musicData.title || musicData.data?.title || 'Generated Music';
    }
    
    // Method 2: Search in tool results data
    const hasMusicTool = toolsUsed.includes('generate_music') || 
      Object.keys(this.pendingTools).some(k => k.startsWith('generate_music'));
    if (!audioUrl && hasMusicTool) {
      const musicResult = toolResultsData['generate_music'];
      if (musicResult) {
        audioUrl = musicResult.audio_url 
          || musicResult.data?.audio_url
          || musicResult.file_url;
        
        if (!audioUrl && musicResult.stash_ref) {
          const stashMatch = musicResult.stash_ref.match(/stash:\/\/([^/]+)\/(.+)/);
          if (stashMatch) {
            audioUrl = `/api/stash/${stashMatch[1]}/${stashMatch[2]}`;
          }
        }
        
        if (!audioUrl && musicResult.file_path) {
          const musicFilename = musicResult.file_path.split('/').pop();
          audioUrl = `/api/music/${musicFilename}`;
        }
        
        audioTitle = musicResult.title || musicResult.data?.title || audioTitle;
      }
    }
    
    if (audioUrl) {
      audioHtml = `
        <div class="message-audio">
          <div class="audio-header">
            <span class="audio-icon">🎵</span>
            <span class="audio-title">${Utils.escapeHtml(audioTitle)}</span>
          </div>
          <audio controls preload="metadata" class="audio-player">
            <source src="${audioUrl}" type="audio/mpeg">
            Your browser does not support audio playback.
          </audio>
        </div>
      `;
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
      const genericVideo = this._findVideoFromToolResults(toolResultsData, ['convert_file']);
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
      Object.keys(this.pendingTools).some(k => k.startsWith('generate_video'));
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
    
    // Check for converted files (from convert_file tool)
    let convertedFileHtml = '';
    const hasConvertTool = toolsUsed.includes('convert_file') || 
      Object.keys(this.pendingTools).some(k => k.startsWith('convert_file'));
    
    if (hasConvertTool) {
      const convertResult = toolResultsData['convert_file'] || data.convert_file;
      if (convertResult && convertResult.stash_ref) {
        const stashMatch = convertResult.stash_ref.match(/stash:\/\/([^/]+)\/(.+)/);
        if (stashMatch) {
          // Use existing stash route: /api/stash/{space_id}/{file_id}
          const stashUrl = `/api/stash/${stashMatch[1]}/${stashMatch[2]}`;
          const targetFormat = convertResult.target_format || '';
          const filename = convertResult.filename || 'converted file';
          const sizeChange = convertResult.size_change || '';
          
          // Check if it's an image format
          const imageFormats = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg', 'bmp', 'ico'];
          const isImage = imageFormats.includes(targetFormat.toLowerCase());
          
          // Check if it's a video format
          const videoFormats = ['mp4', 'webm', 'mov', 'avi', 'mkv'];
          const isVideo = videoFormats.includes(targetFormat.toLowerCase());
          
          // Check if it's an audio format
          const audioFormats = ['mp3', 'wav', 'flac', 'ogg', 'aac', 'm4a'];
          const isAudio = audioFormats.includes(targetFormat.toLowerCase());
          
          // Download button HTML (reusable)
          const downloadBtn = `
            <a href="${stashUrl}" download="${filename}" class="convert-download-btn" title="Download ${filename}">
              ⬇️ Download ${targetFormat.toUpperCase()}
            </a>
          `;
          
          if (isImage) {
            // Display image inline with download button
            convertedFileHtml = `
              <div class="converted-media-container">
                <div class="message-image converted-file" onclick="window.showImageLightbox('${stashUrl}')">
                  <img src="${stashUrl}" alt="Converted ${targetFormat.toUpperCase()}" loading="lazy">
                  <div class="image-overlay">
                    <span>🔍 Click to expand</span>
                  </div>
                </div>
                <div class="convert-actions">
                  <span class="convert-info">${Utils.escapeHtml(filename)} ${sizeChange ? `(${sizeChange})` : ''}</span>
                  ${downloadBtn}
                </div>
              </div>
            `;
          } else if (isVideo) {
            // Display video player with download button
            convertedFileHtml = `
              <div class="converted-media-container">
                <div class="message-video converted-file">
                  <div class="video-header">
                    <span class="video-icon">🎬</span>
                    <span class="video-title">Converted: ${Utils.escapeHtml(filename)}</span>
                  </div>
                  <video controls preload="metadata" class="video-player">
                    <source src="${stashUrl}" type="video/${targetFormat}">
                    Your browser does not support video playback.
                  </video>
                </div>
                <div class="convert-actions">
                  <span class="convert-info">${sizeChange ? `Size: ${sizeChange}` : ''}</span>
                  ${downloadBtn}
                </div>
              </div>
            `;
          } else if (isAudio) {
            // Display audio player with download button
            convertedFileHtml = `
              <div class="converted-media-container">
                <div class="message-audio converted-file">
                  <div class="audio-header">
                    <span class="audio-icon">🎵</span>
                    <span class="audio-title">Converted: ${Utils.escapeHtml(filename)}</span>
                  </div>
                  <audio controls preload="metadata" class="audio-player">
                    <source src="${stashUrl}" type="audio/${targetFormat}">
                    Your browser does not support audio playback.
                  </audio>
                </div>
                <div class="convert-actions">
                  <span class="convert-info">${sizeChange ? `Size: ${sizeChange}` : ''}</span>
                  ${downloadBtn}
                </div>
              </div>
            `;
          } else {
            // Download link for other formats
            convertedFileHtml = `
              <div class="message-file converted-file">
                <a href="${stashUrl}" download="${filename}" class="file-download-link">
                  <span class="file-icon">📁</span>
                  <span class="file-name">${Utils.escapeHtml(filename)}</span>
                  ${sizeChange ? `<span class="file-size">(${sizeChange})</span>` : ''}
                  <span class="download-icon">⬇️</span>
                </a>
              </div>
            `;
          }
        }
      }
    }
    
    // raw_llm_response is inside data.data (nested), also check top level for loaded conversations
    const innerData = data.data || data || {};
    let rawResponse = innerData.raw_llm_response || innerData.vision_analysis || data.raw_llm_response || data.vision_analysis || '';
    if (typeof rawResponse !== 'string') rawResponse = '';
    rawResponse = Utils.stripLlmCitationArtifacts(rawResponse);
    const storedSpeech = Utils.stripLlmCitationArtifacts(String(innerData.speech || data.speech || ''));
    text = Utils.stripLlmCitationArtifacts(text);

    // Shopping/product preview card for focused SerpApi product lookups
    // and single clear product results where a link + image is helpful.
    const serpapiPayload = toolResultsData.serpapi_search || data.serpapi_search;
    const latestSerpapi = Array.isArray(serpapiPayload)
      ? serpapiPayload[serpapiPayload.length - 1]
      : serpapiPayload;

    if (latestSerpapi && typeof latestSerpapi === 'object') {
      const engine = latestSerpapi.engine;
      const results = Array.isArray(latestSerpapi.top_results) && latestSerpapi.top_results.length > 0
        ? latestSerpapi.top_results
        : (Array.isArray(latestSerpapi.results) ? latestSerpapi.results : []);
      const product = results[0];
      const isFocusedProduct =
        engine === 'amazon_product'
        || Boolean(latestSerpapi.asin)
        || (results.length === 1 && engine === 'amazon');

      if (isFocusedProduct && product && product.url && product.title) {
        const title = Utils.escapeHtml(product.title);
        const link = Utils.escapeHtml(product.url);
        const image = (product.image_url || product.thumbnail) ? Utils.escapeHtml(product.image_url || product.thumbnail) : '';
        const price = product.price ? Utils.escapeHtml(String(product.price)) : '';
        const rating = product.rating != null ? Utils.escapeHtml(String(product.rating)) : '';
        const reviews = product.reviews != null ? Utils.escapeHtml(String(product.reviews)) : '';
        const asin = product.asin ? Utils.escapeHtml(String(product.asin)) : '';
        const metaParts = [];
        if (price) metaParts.push(`<span class="product-chip price">${price}</span>`);
        if (rating) metaParts.push(`<span class="product-chip">⭐ ${rating}</span>`);
        if (reviews) metaParts.push(`<span class="product-chip">${reviews} reviews</span>`);
        if (asin) metaParts.push(`<span class="product-chip">ASIN ${asin}</span>`);

        shoppingHtml = `
          <div class="product-preview-card">
            ${image ? `
              <a class="product-preview-image" href="${link}" target="_blank" rel="noopener noreferrer">
                <img src="${image}" alt="${title}" loading="lazy" referrerpolicy="no-referrer">
              </a>
            ` : ''}
            <div class="product-preview-body">
              <div class="product-preview-label">Amazon Product</div>
              <a class="product-preview-title" href="${link}" target="_blank" rel="noopener noreferrer">${title}</a>
              ${metaParts.length ? `<div class="product-preview-meta">${metaParts.join('')}</div>` : ''}
              <div class="product-preview-actions">
                <a class="product-preview-link" href="${link}" target="_blank" rel="noopener noreferrer">Open product</a>
              </div>
            </div>
          </div>
        `;
      }
    }

    const homeDepotPayload = toolResultsData.serpapi_home_depot || data.serpapi_home_depot;
    const latestHomeDepot = Array.isArray(homeDepotPayload)
      ? homeDepotPayload[homeDepotPayload.length - 1]
      : homeDepotPayload;

    if (!shoppingHtml && latestHomeDepot && typeof latestHomeDepot === 'object') {
      const results = Array.isArray(latestHomeDepot.top_results) && latestHomeDepot.top_results.length > 0
        ? latestHomeDepot.top_results
        : (Array.isArray(latestHomeDepot.results) ? latestHomeDepot.results : []);
      const product = latestHomeDepot.product_details || results[0];

      if (product && product.url && product.title) {
        const title = Utils.escapeHtml(product.title);
        const link = Utils.escapeHtml(product.url);
        const image = (product.image_url || product.thumbnail || latestHomeDepot.top_image_url)
          ? Utils.escapeHtml(product.image_url || product.thumbnail || latestHomeDepot.top_image_url)
          : '';
        const price = (product.price_formatted || product.price) ? Utils.escapeHtml(String(product.price_formatted || product.price)) : '';
        const rating = product.rating != null ? Utils.escapeHtml(String(product.rating)) : '';
        const reviews = product.reviews != null ? Utils.escapeHtml(String(product.reviews)) : '';
        const productId = product.product_id ? Utils.escapeHtml(String(product.product_id)) : '';
        const metaParts = [];
        if (price) metaParts.push(`<span class="product-chip price">${price}</span>`);
        if (rating) metaParts.push(`<span class="product-chip">⭐ ${rating}</span>`);
        if (reviews) metaParts.push(`<span class="product-chip">${reviews} reviews</span>`);
        if (productId) metaParts.push(`<span class="product-chip">Product ID ${productId}</span>`);

        shoppingHtml = `
          <div class="product-preview-card">
            ${image ? `
              <a class="product-preview-image" href="${link}" target="_blank" rel="noopener noreferrer">
                <img src="${image}" alt="${title}" loading="lazy" referrerpolicy="no-referrer">
              </a>
            ` : ''}
            <div class="product-preview-body">
              <div class="product-preview-label">Home Depot Product</div>
              <a class="product-preview-title" href="${link}" target="_blank" rel="noopener noreferrer">${title}</a>
              ${metaParts.length ? `<div class="product-preview-meta">${metaParts.join('')}</div>` : ''}
              <div class="product-preview-actions">
                <a class="product-preview-link" href="${link}" target="_blank" rel="noopener noreferrer">Open product</a>
              </div>
            </div>
          </div>
        `;
      }
    }

    const ebayProductPayload = toolResultsData.serpapi_ebay_product || data.serpapi_ebay_product;
    const latestEbayProduct = Array.isArray(ebayProductPayload)
      ? ebayProductPayload[ebayProductPayload.length - 1]
      : ebayProductPayload;

    if (!shoppingHtml && latestEbayProduct && typeof latestEbayProduct === 'object') {
      const results = Array.isArray(latestEbayProduct.top_results) && latestEbayProduct.top_results.length > 0
        ? latestEbayProduct.top_results
        : (Array.isArray(latestEbayProduct.results) ? latestEbayProduct.results : []);
      const summary = latestEbayProduct.product_summary;
      const product = (summary && typeof summary === 'object') ? summary : results[0];

      if (product && product.title) {
        const linkRaw = product.url || (results[0] && results[0].url);
        if (linkRaw) {
          const title = Utils.escapeHtml(product.title);
          const link = Utils.safeHttpUrlForAttr(linkRaw) || Utils.escapeHtml(linkRaw);
          let image = '';
          if (summary && Array.isArray(summary.image_urls) && summary.image_urls.length > 0) {
            image = Utils.safeHttpUrlForAttr(summary.image_urls[summary.image_urls.length - 1])
              || Utils.safeHttpUrlForAttr(summary.image_urls[0]);
          }
          if (!image && product.thumbnail) {
            image = Utils.safeHttpUrlForAttr(product.thumbnail);
          }
          if (!image && latestEbayProduct.top_image_url) {
            image = Utils.safeHttpUrlForAttr(latestEbayProduct.top_image_url);
          }

          let priceStr = '';
          const buy = summary && typeof summary.buy === 'object' ? summary.buy : null;
          if (buy && buy.buy_it_now && typeof buy.buy_it_now === 'object') {
            const pr = buy.buy_it_now.price;
            if (pr && pr.amount != null && pr.currency) {
              priceStr = `${pr.currency} ${pr.amount}`;
            }
          }
          if (!priceStr && buy && buy.bid && typeof buy.bid === 'object') {
            const pr = buy.bid.price;
            if (pr && pr.amount != null && pr.currency) {
              priceStr = `Bid ${pr.currency} ${pr.amount}`;
            }
          }

          const rating = product.rating != null ? Utils.escapeHtml(String(product.rating)) : '';
          const reviews = product.review_count != null ? Utils.escapeHtml(String(product.review_count)) : '';
          const productId = (latestEbayProduct.product_id || product.product_id)
            ? Utils.escapeHtml(String(latestEbayProduct.product_id || product.product_id))
            : '';
          const metaParts = [];
          if (priceStr) metaParts.push(`<span class="product-chip price">${Utils.escapeHtml(priceStr)}</span>`);
          if (rating) metaParts.push(`<span class="product-chip">⭐ ${rating}</span>`);
          if (reviews) metaParts.push(`<span class="product-chip">${reviews} reviews</span>`);
          if (productId) metaParts.push(`<span class="product-chip">Item ${productId}</span>`);

          shoppingHtml = `
          <div class="product-preview-card">
            ${image ? `
              <a class="product-preview-image" href="${link}" target="_blank" rel="noopener noreferrer">
                <img src="${image}" alt="${title}" loading="lazy">
              </a>
            ` : ''}
            <div class="product-preview-body">
              <div class="product-preview-label">eBay Product</div>
              <a class="product-preview-title" href="${link}" target="_blank" rel="noopener noreferrer">${title}</a>
              ${metaParts.length ? `<div class="product-preview-meta">${metaParts.join('')}</div>` : ''}
              <div class="product-preview-actions">
                <a class="product-preview-link" href="${link}" target="_blank" rel="noopener noreferrer">Open listing</a>
              </div>
            </div>
          </div>
        `;
        }
      }
    }

    const canvasPreview = this._extractCanvasPreview(toolResultsData, data);
    const canvasPreviewHtml = canvasPreview
      ? this._renderCanvasPreviewHtml(canvasPreview)
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
      ${canvasPreviewHtml}
      ${shoppingHtml}
      ${imageHtml}
      ${convertedFileHtml}
      ${audioHtml}
      ${videoHtml}
      ${youtubeEmbedsHtml}
      ${messageBubbleHtml}
      ${toolsUsed.includes('canvas') ? '' : `
        <div class="message-actions send-to-canvas-actions">
          <button type="button" class="message-action-btn send-to-canvas-btn" title="Create a Canvas page from this response and its supporting context">
            <span aria-hidden="true">📄</span> Send to Canvas
          </button>
        </div>
      `}
    `;

    const sendToCanvasBtn = messageEl.querySelector('.send-to-canvas-btn');
    if (sendToCanvasBtn) {
      sendToCanvasBtn.addEventListener('click', () => {
        this.sendResponseToCanvas(text, sendToCanvasBtn);
      });
    }
    
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

    this._attachCompletionGuardCard(messageEl, data, toolsUsed);
    
    this.messagesContainer.appendChild(messageEl);
    Utils.hydrateRichContent(messageEl);
    if (canvasPreview) {
      this._hydrateCanvasPreview(messageEl, canvasPreview);
    }
    Utils.scrollToBottom(this.messagesContainer);
    
    // Clear only this response's pending tool state. Late events from another
    // message remain isolated instead of contaminating the next response.
    this._clearPendingToolsForMessage(liveMessageId);
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
        status: entry.ok === false ? 'error' : 'success',
        result: entry.ok === false
          ? this._getToolTraceFailureResult(entry)
          : this._getToolTraceSuccessFallback(entry),
        args: entry.arguments || {},
        duration: entry.duration_ms ?? null
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
      const queued = entriesByTool.get(toolName)?.shift();
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
      if (toolData.result === null || toolData.result === undefined) toolData.result = entry.result;
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
      'Preserve useful source links and any image, video, audio, or stash references so Canvas can render the original media.',
      'Use a descriptive title and organize the result as readable Markdown.',
      excerpt ? `The selected response begins: "${excerpt}"` : ''
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
        const parsed = new URL(pageUrl);
        if (!['http:', 'https:'].includes(parsed.protocol)) continue;
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
    const filePath = toolResult.file_path || saved.path || saved.file_path || '';
    const filename = toolResult.filename
      || toolResult.name
      || saved.filename
      || (filePath ? String(filePath).split('/').pop() : '');

    return {
      stashRef: toolResult.stash_ref || toolResult.ref || saved.stash_ref || saved.ref || null,
      filename,
      mimeType: String(toolResult.mime_type || saved.mime_type || '').toLowerCase(),
      directUrl: toolResult.video_url || toolResult.file_url || toolResult.url || null,
      title: toolResult.video_title
        || toolResult.title
        || toolResult.prompt
        || toolResult.subject
        || null,
      duration: toolResult.duration_seconds || toolResult.duration || toolResult.data?.duration || '',
      hasAudio: toolResult.has_audio || false,
      provider: toolResult.provider || '',
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

  /** Pull SerpApi YouTube tool payloads (possibly arrays) for iframe embedding. */
  _youtubeToolPayloadsForEmbeds(toolResultsData = {}) {
    const out = [];
    if (!toolResultsData || typeof toolResultsData !== 'object') return out;
    for (const key of ['serpapi_youtube_search', 'serpapi_youtube']) {
      const tr = toolResultsData[key];
      if (!tr) continue;
      if (Array.isArray(tr)) {
        for (const item of tr) {
          if (item && typeof item === 'object') out.push(item);
        }
      } else if (typeof tr === 'object') {
        out.push(tr);
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

    for (const payload of this._youtubeToolPayloadsForEmbeds(toolResultsData)) {
      const primaryTitle = typeof payload.title === 'string' ? payload.title.trim() : '';
      if (payload.top_url) {
        const vid = this._extractYouTubeVideoId(payload.top_url);
        if (vid) pushEmbed(vid, primaryTitle);
      }
      if (typeof payload.url === 'string') {
        const vid = this._extractYouTubeVideoId(payload.url);
        if (vid) pushEmbed(vid, primaryTitle);
      }
      if (payload.video_id != null && String(payload.video_id).trim()) {
        pushEmbed(String(payload.video_id).trim(), primaryTitle);
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
            if (vid) pushEmbed(vid, hint);
          } else if (item.video_id != null && String(item.video_id).trim()) {
            pushEmbed(String(item.video_id).trim(), hint);
          }
        }
      }
    }

    const sources = [displayText, rawResponse];

    for (const source of sources) {
      if (!source || embeds.length >= maxEmbeds) continue;

      const matches = String(source).match(urlRegex) || [];
      for (const rawUrl of matches) {
        if (embeds.length >= maxEmbeds) break;

        const videoId = this._extractYouTubeVideoId(rawUrl);
        if (!videoId || seenIds.has(videoId) || downloadedIds.has(videoId)) continue;

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
    // Remove existing thinking indicator
    this.hideThinking();
    
    // Show stop button
    if (this.stopBtn) {
      this.stopBtn.style.display = 'flex';
    }
    
    const thinkingEl = document.createElement('div');
    thinkingEl.className = 'message assistant thinking-message';
    thinkingEl.innerHTML = `
      <div class="thinking-indicator">
        <div class="thinking-dots">
          <span></span>
          <span></span>
          <span></span>
        </div>
        <span class="thinking-label">Thinking...</span>
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

  _markToolStarted(data = {}) {
    this.activeToolCalls.add(this._processingToolKey(data));
    if (this.activeToolCalls.size !== 1) return;

    if (this._workingLabelTimer) clearTimeout(this._workingLabelTimer);
    this._workingLabelTimer = setTimeout(() => {
      this._workingLabelTimer = null;
      if (this.activeToolCalls.size === 0) return;
      this._workingLabelVisible = true;
      this._setProcessingLabel('Working...');
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
      this._setProcessingLabel('Reviewing results...');
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

  _handleCompletionGuardTerminalUi(data) {
    const terminalStatuses = new Set(['tighten_only', 'cancelled', 'ticket_created', 'error']);
    if (!terminalStatuses.has(data?.status)) {
      return;
    }

    this._resetProcessingUi();
    this.currentMessageId = null;
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
   * @param {string} status - Status: 'pending', 'success', 'error'
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
   * @param {string} status - Status: 'pending', 'success', 'error'
   * @param {object} result - Tool result data
   * @param {number} duration - Duration in ms
   */
  updateToolCard(cardId, toolName, status, result = {}, duration = null) {
    // Handle legacy calls with 4 args (cardId = toolName)
    if (typeof toolName !== 'string' || ['pending', 'success', 'error'].includes(toolName)) {
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
    
    card.className = `tool-card ${status}`;
    
    const statusEl = card.querySelector('.tool-card-status');
    if (statusEl) {
      if (status === 'success') {
        statusEl.innerHTML = `✅ ${duration ? Utils.formatDuration(duration) : 'Complete'}`;
      } else if (status === 'error') {
        statusEl.innerHTML = `❌ Failed`;
      } else if (result.progress !== undefined) {
        statusEl.innerHTML = `⏳ ${result.progress}%`;
      }
    }
    
    const bodyEl = card.querySelector('.tool-card-body');
    if (bodyEl && result) {
      const summary = typeof result === 'object' ? Utils.formatJson(result) : String(result);
      bodyEl.innerHTML = Utils.escapeHtmlAndLinkify(summary);
    }
  }

  /**
   * Create tool card HTML
   */
  _createToolCardHtml(toolName, status, data, duration = null) {
    const statusText = status === 'pending' 
      ? '⏳ Running...' 
      : status === 'success' 
        ? `✅ ${duration ? Utils.formatDuration(duration) : 'Complete'}`
        : '❌ Failed';
    
    // Show full JSON - user can scroll in expanded view
    let summary = '';
    if (data && typeof data === 'object') {
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
      <div class="tool-card ${status}">
        <div class="tool-card-header">
          <span class="tool-card-title">${Utils.escapeHtml(toolName)}</span>
          <span class="tool-card-status">${statusText}</span>
        </div>
        ${detailsLinkHtml}
        <pre class="tool-card-body">${Utils.escapeHtmlAndLinkify(summary)}</pre>
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
      if (status !== 'error') {
        successfulToolOccurrenceCounts[displayName] = resultOccurrenceIndex + 1;
      }
      const result = status === 'error'
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
    if (!Array.isArray(trace)) return [];
    return trace.filter(entry => entry && typeof entry === 'object' && entry.tool);
  }

  _getToolTraceFailureResult(entry = {}) {
    return {
      error: entry.error || entry.speech || 'Tool failed',
      arguments: entry.arguments || {}
    };
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
      // Card doesn't exist, create it and retry
      this._showFeedbackCard('analyzing', data?.message_id);
      setTimeout(() => this._updateFeedbackCard(data), 100);
      return;
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
    this.feedbackEnabled = !this.feedbackEnabled;
    
    // Update button state
    const feedbackBtn = document.getElementById('feedbackBtn');
    if (feedbackBtn) {
      feedbackBtn.classList.toggle('active', this.feedbackEnabled);
      feedbackBtn.title = this.feedbackEnabled ? 'Feedback ON - Click to disable' : 'Feedback OFF - Click to enable';
    }
    
    Utils.toast(
      this.feedbackEnabled ? '📊 Feedback enabled for next message' : '📊 Feedback disabled',
      'info',
      2000
    );
  }

  /**
   * Update send button state
   */
  updateSendButton() {
    this.sendBtn.disabled = this.isProcessing;
    this.sendBtn.innerHTML = this.isProcessing ? '⏳' : '➤';
  }
  
  /**
   * Cancel current processing
   */
  cancelProcessing() {
    if (!this.isProcessing && !this.currentMessageId) return;
    
    console.log('[ChatUI] Canceling processing...');
    
    // Send cancel event to server
    if (window.jarvisSocket && window.jarvisSocket.socket) {
      window.jarvisSocket.socket.emit('cancel', {
        message_id: this.currentMessageId
      });
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
    if (!contextWindow && provider) {
      contextWindow = await this._resolveContextWindowForProviderModel(provider, model, mode);
    }
    this.tokenStatsMeta = { provider, model, mode, billingMode, contextWindow };

    this._renderTokenCount();
    this._renderCostLabel();
    this.tokenCounterEl.style.display = 'flex';
    this._renderTokenTooltip();
  }

  /**
   * Clear chat history
   */
  clearChat() {
    this._resetProcessingUi();
    this.currentMessageId = null;
    this._resetPendingToolState();

    // Keep only the welcome message
    const messages = this.messagesContainer.querySelectorAll('.message');
    messages.forEach((msg, index) => {
      if (index > 0) msg.remove();
    });
    
    // Reset token counter for new chat
    this._resetTokenCounter();
  }
}

// Create global instance
window.chatUI = new ChatUI();
