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
    this.loaded = false;
    this._loadRegistry();
  }
  
  /**
   * Load prompts and workflows from server
   */
  async _loadRegistry() {
    try {
      // Load prompts and workflows in parallel
      const [promptsRes, workflowsRes] = await Promise.all([
        fetch('/api/prompts'),
        fetch('/api/workflows')
      ]);
      
      if (promptsRes.ok) {
        const data = await promptsRes.json();
        this.prompts = data.prompts || {};
      }
      
      if (workflowsRes.ok) {
        const data = await workflowsRes.json();
        this.workflows = data.workflows || {};
      }
      
      this.loaded = true;
      console.log('[Commands] Loaded:', Object.keys(this.prompts).length, 'prompts,',
                  Object.keys(this.workflows || {}).length, 'workflows');
    } catch (err) {
      console.warn('[Commands] Failed to load registry:', err);
    }
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
    
    // Sort alphabetically by name and limit to 30 suggestions
    return suggestions
      .sort((a, b) => a.name.localeCompare(b.name))
      .slice(0, 30);
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
    return parts.join(' + ');
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
    this.imagePreview = document.getElementById('imagePreview');
    this.removeImageBtn = document.getElementById('removeImageBtn');
    
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
    this.pendingImageData = null;  // Temp storage while modal is open
    
    this.currentMessageId = null;
    this.pendingTools = {};
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
    this.attachedImage = null;  // {base64, url, filename}
    
    // Autocomplete state
    this.autocompleteEl = null;
    this.selectedSuggestionIndex = -1;
    
    // Token/cost tracking state
    this.tokenCounterEl = document.getElementById('tokenCounter');
    this.tokenCountEl = document.getElementById('tokenCount');
    this.tokenCostEl = document.getElementById('tokenCost');
    this.cumulativeTokens = { input: 0, output: 0, total: 0 };
    this.cumulativeCost = 0;
    this.contextWindow = 2000000;  // Default to xAI's 2M, updated from server
    this.llmProvider = 'xai';      // Default, updated from server
    
    this._setupEventListeners();
    this._setupSocketListeners();
    this._setupVoiceRecording();
    this._setupImageUpload();
    this._setupImageActionModal();
    this._setupFileConversion();
    this._setupAutocomplete();
    this._setupEnhanceButton();
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
      const res = await fetch('/api/settings');
      if (res.ok) {
        const data = await res.json();
        const settings = data.settings || {};
        
        // Get effective provider from settings (includes UI overrides)
        const provider = settings.llm?.provider?.value || 'xai';
        const currentMode = settings.mode || mode || 'cloud';
        
        // Set context window based on LLM provider (not TTS)
        if (provider === 'xai') {
          // grok-4-fast models have 2M context
          this.contextWindow = 2000000;
        } else if (provider === 'anthropic') {
          this.contextWindow = 200000;
        } else if (provider === 'openai') {
          this.contextWindow = 128000;
        } else if (provider === 'ollama') {
          // Local models - check for configured context window
          // Try to get from system config as a fallback
          try {
            const sysRes = await fetch(`/api/settings/system?mode=${currentMode}`);
            if (sysRes.ok) {
              const sysConfig = await sysRes.json();
              this.contextWindow = parseInt(sysConfig.OLLAMA_CONTEXT_WINDOW) || 32768;
            } else {
              this.contextWindow = 32768;
            }
          } catch {
            this.contextWindow = 32768;
          }
        }
        
        this.llmProvider = provider;  // Store for display
        console.log('[Chat] LLM Provider:', provider, '| Context window:', this.contextWindow.toLocaleString(), 'tokens');
      }
    } catch (err) {
      console.warn('[Chat] Could not fetch context window:', err);
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
    
    // Show loading state
    this.enhanceBtn.classList.add('enhancing');
    this.enhanceBtn.disabled = true;
    const originalTitle = this.enhanceBtn.title;
    this.enhanceBtn.title = 'Enhancing...';
    
    try {
      const response = await fetch('/api/enhance-prompt', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ input })
      });
      
      const data = await response.json();
      
      if (data.ok && data.enhanced) {
        // Replace input with enhanced version
        this.inputField.value = data.enhanced;
        Utils.autoResize(this.inputField);
        
        // Show success feedback
        Utils.toast('✨ Prompt enhanced!', 'success', 2000);
        
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
    
    // Case 1: Start with / and no space yet (typing workflow)
    if (input.startsWith('/') && !input.includes(' ')) {
      const suggestions = window.commandSystem.getSuggestions(input);
      if (suggestions.length > 0) {
        this._showAutocomplete(suggestions);
        return;
      }
    }
    
    // Case 2: Start with @ and no space yet (typing prompt only)
    if (input.startsWith('@') && !input.includes(' ')) {
      const suggestions = window.commandSystem.getSuggestions(input);
      if (suggestions.length > 0) {
        this._showAutocomplete(suggestions);
        return;
      }
    }
    
    // Case 3: Start with * and no space yet (bookmark search - Firefox-style)
    if (input.startsWith('*') && !input.includes(' ')) {
      const suggestions = window.commandSystem.getSuggestions(input);
      if (suggestions.length > 0) {
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
        const tooltip = item.querySelector('.workflow-tooltip, .prompt-tooltip');
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
        const tooltip = item.querySelector('.workflow-tooltip, .prompt-tooltip');
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
      this.isProcessing = true;
      this.updateSendButton();
      this.showThinking();
    });
    
    socket.on('toolStart', (data) => {
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
      // Use call_index for unique card ID when same tool called multiple times
      const cardId = data.call_index > 0 ? `${data.tool}_${data.call_index}` : data.tool;
      this.updateToolCard(cardId, data.tool, 'error', { error: data.error });
    });
    
    socket.on('response', (data) => {
      this.hideThinking();
      this.clearStatus();  // Clear any status messages
      this.addAssistantMessage(data.text, data.tools_used, data);
      this.currentMessageId = null;
      this.isProcessing = false;
      this.updateSendButton();
      
      // Update token counter if usage data available
      if (data.usage) {
        this._updateTokenCounter(data.usage);
      }
      
      // Show discrete toast for server-side tools (xAI/Anthropic native search)
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
      this.currentMessageId = null;
      this.isProcessing = false;
      this.updateSendButton();
    });

    socket.on('cancelled', (data) => {
      this.hideThinking();
      this.clearStatus();
      this.isProcessing = false;
      this.updateSendButton();

      if (data?.message_id && this.currentMessageId === data.message_id) {
        this.currentMessageId = null;
      }

      Utils.toast('Stopped current task', 'info', 2500);
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
      this._updateCompletionGuardCard({
        ...data,
        status: 'error'
      });
      Utils.toast(data.error || 'Completion Guard failed', 'error', 4000);
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
      const file = e.target.files[0];
      if (file) {
        await this.attachFile(file);
      }
      // Reset input so same file can be selected again
      this.fileInput.value = '';
    });
    
    // Remove image button
    if (this.removeImageBtn) {
      this.removeImageBtn.addEventListener('click', () => {
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
        
        const file = e.dataTransfer.files[0];
        if (file) {
          await this.attachFile(file);
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
    
    console.log('[Chat] Image action modal ready');
  }
  
  /**
   * Show the image action modal with preview
   */
  _showImageActionModal(uploadData) {
    if (!this.imageActionModal) return;
    
    // Store upload data temporarily
    this.pendingImageData = uploadData;
    
    // Show image preview
    if (this.imageActionPreview) {
      this.imageActionPreview.innerHTML = '';
      const img = document.createElement('img');
      img.src = uploadData.url;
      img.style.maxWidth = '200px';
      img.style.maxHeight = '150px';
      img.style.borderRadius = 'var(--radius-md)';
      this.imageActionPreview.appendChild(img);
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
    this.pendingImageData = null;
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
    
    // Update provider-specific options if image panel is now visible
    if (selected === 'image') {
      this._updateImageProviderOptions();
    }
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
    if (videoProvider) videoProvider.value = 'xai';
    if (videoRatio) videoRatio.value = '16:9';
    if (videoDuration) videoDuration.value = '5';
    if (videoResolution) videoResolution.value = '720p';
    
    // Image options
    const imageProvider = document.getElementById('imgActionImageProvider');
    const imageRatio = document.getElementById('imgActionImageRatio');
    const imageSize = document.getElementById('imgActionImageSize');
    const imageStyle = document.getElementById('imgActionImageStyle');
    if (imageProvider) imageProvider.value = 'gemini';
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
        const transparent = document.getElementById('imgActionTransparent')?.checked;
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
    if (!this.pendingImageData) return;
    
    const { action, settings } = this._collectImageActionSettings();
    
    // Store the image data with action and settings
    this.attachedImage = {
      base64: this.pendingImageData.base64,
      url: this.pendingImageData.url,
      filename: this.pendingImageData.filename,
      action: action,
      settings: settings
    };
    
    // Show preview with action badge
    this._showImagePreviewWithBadge(this.pendingImageData.url, action, settings);
    
    // Close modal and focus input
    this._hideImageActionModal();
    this.inputField.focus();
    
    // Toast with action info
    const actionLabels = { analyze: 'Analyze', video: 'Video', image: 'Image' };
    Utils.toast(`Image attached: ${actionLabels[action] || action}`, 'success', 1500);
  }
  
  /**
   * Show image preview with an action badge overlay
   */
  _showImagePreviewWithBadge(url, action, settings) {
    if (this.imagePreview && this.imagePreviewContainer) {
      this.imagePreview.src = url;
      this.imagePreviewContainer.style.display = 'block';
      
      // Remove any existing badge
      const existingBadge = this.imagePreviewContainer.querySelector('.image-action-badge');
      if (existingBadge) existingBadge.remove();
      
      // Build badge text
      let badgeText = '';
      if (action === 'video') {
        badgeText = `VIDEO ${settings.aspect_ratio || ''} ${settings.duration || 5}s`;
      } else if (action === 'image') {
        badgeText = `IMAGE ${settings.provider || ''}`;
      } else {
        badgeText = 'ANALYZE';
      }
      
      // Add badge
      const badge = document.createElement('span');
      badge.className = 'image-action-badge';
      badge.textContent = badgeText;
      badge.style.cssText = 'position: absolute; top: 4px; left: 4px; background: rgba(0,0,0,0.7); color: #fff; font-size: 10px; padding: 2px 6px; border-radius: 4px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px;';
      
      // Make sure container is positioned for absolute badge
      const previewDiv = this.imagePreviewContainer.querySelector('.image-preview');
      if (previewDiv) {
        previewDiv.style.position = 'relative';
        previewDiv.appendChild(badge);
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
    // Validate file type
    if (!file.type.startsWith('image/')) {
      Utils.toast('Please select an image file', 'error');
      return;
    }
    
    // Clear any existing text file attachment
    this.clearAttachedFile();
    
    // Validate file size (max 10MB)
    if (file.size > 10 * 1024 * 1024) {
      Utils.toast('Image too large (max 10MB)', 'error');
      return;
    }
    
    try {
      Utils.toast('Uploading image...', 'info', 1500);
      
      const formData = new FormData();
      formData.append('image', file);
      
      const response = await fetch('/api/upload-image', {
        method: 'POST',
        body: formData
      });
      
      const data = await response.json();
      
      if (data.ok) {
        // Show image action modal to let user choose what to do
        this._showImageActionModal(data);
      } else {
        Utils.toast(data.error || 'Failed to upload image', 'error');
      }
    } catch (err) {
      console.error('[Chat] Image upload error:', err);
      Utils.toast('Failed to upload image', 'error');
    }
  }
  
  /**
   * Show image preview in input area
   */
  showImagePreview(url) {
    if (this.imagePreview && this.imagePreviewContainer) {
      this.imagePreview.src = url;
      this.imagePreviewContainer.style.display = 'block';
    }
  }
  
  /**
   * Clear attached image
   */
  clearAttachedImage() {
    this.attachedImage = null;
    if (this.imagePreviewContainer) {
      this.imagePreviewContainer.style.display = 'none';
      // Remove any action badge
      const badge = this.imagePreviewContainer.querySelector('.image-action-badge');
      if (badge) badge.remove();
    }
    if (this.imagePreview) {
      this.imagePreview.src = '';
    }
  }

  /**
   * Send a message (with optional attached image or text file)
   */
  sendMessage() {
    let rawMessage = this.inputField.value.trim();
    const hasImage = this.attachedImage !== null;
    const hasFile = this.attachedFile !== null;
    
    // Need either message, image, or file
    if (!rawMessage && !hasImage && !hasFile) return;
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
    
    // Parse workflows and prompts
    const parsed = window.commandSystem.parseInput(rawMessage);
    
    // Build display message (show original with decorations, show feedback badge if enabled)
    let displayMessage = this.inputField.value.trim();  // Use original for display
    let activeBadge = '';
    if (parsed.workflow || parsed.prompt) {
      activeBadge = window.commandSystem.getActiveDisplay(parsed);
    }
    if (requestFeedback) {
      activeBadge += (activeBadge ? ' ' : '') + '<span class="badge badge-feedback">📊</span>';
    }
    
    // Add file attachment indicator to display if text file attached
    if (hasFile) {
      const fileLabel = `📄 ${this.attachedFile.name}`;
      displayMessage = displayMessage ? `${fileLabel}\n${displayMessage}` : fileLabel;
    }
    
    // Add user message to UI (with image if attached)
    this.addUserMessage(displayMessage, this.attachedImage, activeBadge);
    
    // Clear input
    this.inputField.value = '';
    Utils.autoResize(this.inputField);
    
    // Send via socket (include image data, prompt metadata, and feedback request)
    this.isProcessing = true;
    this.updateSendButton();
    this.pendingTools = {};
    
    // Pass parsed data to socket (workflows are handled by orchestrator via /trigger)
    window.jarvisSocket.sendMessage(parsed.message || rawMessage, this.attachedImage, {
      system_instruction: parsed.instruction,
      prompt_name: parsed.prompt
    }, requestFeedback, this.attachedFile);
    
    // Clear attachments after sending
    this.clearAttachedImage();
    this.clearAttachedFile();
  }

  /**
   * Add user message to chat (with optional image and active badge)
   */
  addUserMessage(text, imageData = null, activeBadge = '') {
    const messageEl = document.createElement('div');
    messageEl.className = 'message user';
    
    let imageHtml = '';
    if (imageData && imageData.url) {
      imageHtml = `
        <div class="message-image" onclick="window.showImageLightbox('${imageData.url}')">
          <img src="${imageData.url}" alt="Attached image" loading="lazy">
          <div class="image-overlay">
            <span>🔍 Click to expand</span>
          </div>
        </div>`;
    }
    
    let badgeHtml = '';
    if (activeBadge) {
      // Don't escape - activeBadge may contain valid HTML (like feedback badge)
      badgeHtml = `<div class="command-badge">${activeBadge}</div>`;
    }
    
    messageEl.innerHTML = `
      <div class="message-bubble">
        ${badgeHtml}
        ${imageHtml}
        ${text ? Utils.escapeHtml(text) : '<em>What\'s in this image?</em>'}
      </div>
    `;
    
    this.messagesContainer.appendChild(messageEl);
    Utils.scrollToBottom(this.messagesContainer);
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
    // Workflow messages store tool output in data.results (array); build flat map for loading
    if (data.results && Array.isArray(data.results)) {
      const flat = {};
      for (const step of data.results) {
        const tool = step.tool || 'unknown';
        const stepOutput = step.outputs
          ? (step.outputs[0]?.data ?? step.outputs[0] ?? {})
          : (step.data ?? {});
        flat[tool] = stepOutput;
      }
      toolResultsData = { ...toolResultsData, ...flat };
    }
    let toolCardsHtml = '';
    const pendingToolEntries = Object.entries(this.pendingTools);
    if (pendingToolEntries.length > 0) {
      toolCardsHtml = '<div class="tool-cards">';
      for (const [cardId, toolData] of pendingToolEntries) {
        // Get display name - either stored toolName or extract from cardId
        const displayName = toolData.toolName || cardId.replace(/_step\d+$/, '');
        const toolResult = toolResultsData[displayName] || toolData.result || {};
        toolCardsHtml += this._createToolCardHtml(
          displayName,
          toolData.status || 'success',
          toolResult,
          toolData.duration
        );
      }
      toolCardsHtml += '</div>';
    } else if (toolsUsed.length > 0) {
      // Fallback for non-workflow responses
      toolCardsHtml = '<div class="tool-cards">';
      for (const tool of toolsUsed) {
        const toolResult = toolResultsData[tool] || {};
        toolCardsHtml += this._createToolCardHtml(tool, 'success', toolResult, null);
      }
      toolCardsHtml += '</div>';
    }
    
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
    
    // Method 1: Check data.generate_video object
    const videoData = data.generate_video;
    if (videoData && typeof videoData === 'object') {
      // Try various paths for video URL - prefer local file over remote URL
      const savedInfo = videoData.saved || videoData.data?.saved;
      if (savedInfo?.filename) {
        videoUrl = `/api/videos/${savedInfo.filename}`;
      }
      
      // Fallback to stash reference
      if (!videoUrl && videoData.stash_ref) {
        const stashMatch = videoData.stash_ref.match(/stash:\/\/([^/]+)\/(.+)/);
        if (stashMatch) {
          videoUrl = `/api/stash/${stashMatch[1]}/${stashMatch[2]}`;
        }
      }
      
      // Fallback to file_path
      if (!videoUrl && videoData.file_path) {
        const videoFilename = videoData.file_path.split('/').pop();
        videoUrl = `/api/videos/${videoFilename}`;
      }
      
      // Last resort: remote URL (may expire)
      if (!videoUrl && videoData.video_url) {
        videoUrl = videoData.video_url;
      }
      
      // Get duration, title, audio, and provider
      videoDuration = videoData.duration || videoData.data?.duration || '';
      videoHasAudio = videoData.has_audio || videoData.data?.has_audio || false;
      videoProvider = videoData.provider || videoData.data?.provider || '';
      videoTitle = videoData.prompt 
        ? `Generated Video: ${videoData.prompt.substring(0, 50)}${videoData.prompt.length > 50 ? '...' : ''}`
        : 'Generated Video';
    }
    
    // Method 1.5: Generic stash_ref video for non-generate tools (e.g., youtube_video)
    const toolsWithOwnVideoDisplay = ['generate_video', 'convert_file'];
    if (!videoUrl) {
      const videoExtensions = /\.(mp4|webm|mov|avi|mkv|m4v)$/i;
      for (const [toolName, toolResult] of Object.entries(toolResultsData)) {
        if (toolsWithOwnVideoDisplay.includes(toolName)) continue;
        if (!toolResult || typeof toolResult !== 'object') continue;

        const ref = toolResult.stash_ref || toolResult.ref;
        if (!ref) continue;

        const fn = toolResult.filename || toolResult.name || '';
        const mime = (toolResult.mime_type || '').toLowerCase();
        const isVideo = videoExtensions.test(fn) || mime.startsWith('video/');
        if (!isVideo) continue;

        const stashMatch = ref.match(/stash:\/\/([^/]+)\/(.+)/);
        if (!stashMatch) continue;

        videoUrl = `/api/stash/${stashMatch[1]}/${stashMatch[2]}`;
        videoTitle = toolResult.video_title || toolResult.title || (fn ? `Video: ${fn}` : 'Video');
        videoDuration = toolResult.duration_seconds || toolResult.duration || '';
        videoHasAudio = toolResult.has_audio || false;
        videoProvider = toolResult.provider || '';
        break;
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
        }
        
        if (!videoUrl && videoResult.stash_ref) {
          const stashMatch = videoResult.stash_ref.match(/stash:\/\/([^/]+)\/(.+)/);
          if (stashMatch) {
            videoUrl = `/api/stash/${stashMatch[1]}/${stashMatch[2]}`;
          }
        }
        
        if (!videoUrl && videoResult.file_path) {
          const videoFilename = videoResult.file_path.split('/').pop();
          videoUrl = `/api/videos/${videoFilename}`;
        }
        
        if (!videoUrl && videoResult.video_url) {
          videoUrl = videoResult.video_url;
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
      videoHtml = `
        <div class="message-video">
          <div class="video-header">
            <span class="video-icon">🎬</span>
            <span class="video-title">${Utils.escapeHtml(videoTitle)}</span>
          </div>
          <video controls preload="metadata" class="video-player">
            <source src="${videoUrl}" type="video/mp4">
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
    const rawResponse = innerData.raw_llm_response || innerData.vision_analysis || data.raw_llm_response || data.vision_analysis || '';
    const storedSpeech = innerData.speech || data.speech || '';

    // Prefer the richer raw response for chat display when it is the same answer with
    // better visual structure. This keeps TTS concise while avoiding paragraph blobs.
    if (this._shouldPreferRawForDisplay(rawResponse, storedSpeech, text)) {
      text = rawResponse;
    }

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
    
    messageEl.innerHTML = `
      ${toolCardsHtml}
      ${imageHtml}
      ${convertedFileHtml}
      ${audioHtml}
      ${videoHtml}
      <div class="message-bubble">
        ${parsedText}
        ${detailsHtml}
      </div>
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

    this._attachCompletionGuardCard(messageEl, data, toolsUsed);
    
    this.messagesContainer.appendChild(messageEl);
    Utils.scrollToBottom(this.messagesContainer);
    
    // Clear pending tools
    this.pendingTools = {};
  }

  _normalizeDisplayText(text) {
    if (!text) return '';
    return String(text)
      .replace(/[*_`#>]+/g, '')
      .replace(/\s+/g, ' ')
      .trim();
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
        <span>Thinking...</span>
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
    
    return `
      <div class="tool-card ${status}">
        <div class="tool-card-header">
          <span class="tool-card-title">${Utils.escapeHtml(toolName)}</span>
          <span class="tool-card-status">${statusText}</span>
        </div>
        <pre class="tool-card-body">${Utils.escapeHtmlAndLinkify(summary)}</pre>
      </div>
    `;
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
   * @param {Object} usage - {input_tokens, output_tokens, total_tokens, cost_usd}
   */
  _updateTokenCounter(usage) {
    if (!this.tokenCounterEl) return;
    
    // Accumulate tokens
    const inputTokens = usage.input_tokens || 0;
    const outputTokens = usage.output_tokens || 0;
    const totalTokens = usage.total_tokens || (inputTokens + outputTokens);
    const cost = usage.cost_usd || 0;
    
    this.cumulativeTokens.input += inputTokens;
    this.cumulativeTokens.output += outputTokens;
    this.cumulativeTokens.total += totalTokens;
    this.cumulativeCost += cost;
    
    // Format token count
    const tokenStr = this.cumulativeTokens.total.toLocaleString();
    this.tokenCountEl.textContent = `${tokenStr} tokens`;
    
    // Show cost only for cloud mode (cost > 0)
    if (this.cumulativeCost > 0) {
      // Format cost nicely
      const costStr = this.cumulativeCost < 0.01 
        ? `$${this.cumulativeCost.toFixed(4)}` 
        : `$${this.cumulativeCost.toFixed(2)}`;
      this.tokenCostEl.textContent = costStr;
    } else {
      this.tokenCostEl.textContent = '';
    }
    
    // Show the counter
    this.tokenCounterEl.style.display = 'flex';
    
    // Add warning classes based on context usage
    const usagePercent = (this.cumulativeTokens.total / this.contextWindow) * 100;
    this.tokenCounterEl.classList.remove('warning', 'danger');
    
    // Build tooltip with provider info
    const providerInfo = this.llmProvider ? ` (${this.llmProvider.toUpperCase()})` : '';
    
    if (usagePercent > 80) {
      this.tokenCounterEl.classList.add('danger');
      this.tokenCounterEl.title = `⚠️ ${usagePercent.toFixed(0)}% of ${this.contextWindow.toLocaleString()} context used${providerInfo}`;
    } else if (usagePercent > 50) {
      this.tokenCounterEl.classList.add('warning');
      this.tokenCounterEl.title = `${usagePercent.toFixed(0)}% of ${this.contextWindow.toLocaleString()} context used${providerInfo}`;
    } else {
      this.tokenCounterEl.title = `${usagePercent.toFixed(1)}% of ${this.contextWindow.toLocaleString()} token context${providerInfo}`;
    }
  }

  /**
   * Reset token counter (for new chat)
   */
  _resetTokenCounter() {
    this.cumulativeTokens = { input: 0, output: 0, total: 0 };
    this.cumulativeCost = 0;
    
    if (this.tokenCounterEl) {
      this.tokenCounterEl.style.display = 'none';
      this.tokenCounterEl.classList.remove('warning', 'danger');
    }
    if (this.tokenCountEl) {
      this.tokenCountEl.textContent = '0 tokens';
    }
    if (this.tokenCostEl) {
      this.tokenCostEl.textContent = '';
    }
  }

  /**
   * Restore token counter from historical data (when loading a conversation)
   * @param {Object} tokens - {input, output, total}
   * @param {number} cost - cumulative cost in USD
   */
  restoreTokenCounter(tokens, cost) {
    if (!this.tokenCounterEl) return;
    
    // Set cumulative values
    this.cumulativeTokens = { ...tokens };
    this.cumulativeCost = cost || 0;
    
    // Format and display
    const tokenStr = this.cumulativeTokens.total.toLocaleString();
    this.tokenCountEl.textContent = `${tokenStr} tokens`;
    
    // Show cost only for cloud mode (cost > 0)
    if (this.cumulativeCost > 0) {
      const costStr = this.cumulativeCost < 0.01 
        ? `$${this.cumulativeCost.toFixed(4)}` 
        : `$${this.cumulativeCost.toFixed(2)}`;
      this.tokenCostEl.textContent = costStr;
    } else {
      this.tokenCostEl.textContent = '';
    }
    
    // Show the counter
    this.tokenCounterEl.style.display = 'flex';
    
    // Update warning classes
    const usagePercent = (this.cumulativeTokens.total / this.contextWindow) * 100;
    this.tokenCounterEl.classList.remove('warning', 'danger');
    
    const providerInfo = this.llmProvider ? ` (${this.llmProvider.toUpperCase()})` : '';
    
    if (usagePercent > 80) {
      this.tokenCounterEl.classList.add('danger');
      this.tokenCounterEl.title = `⚠️ ${usagePercent.toFixed(0)}% of ${this.contextWindow.toLocaleString()} context used${providerInfo}`;
    } else if (usagePercent > 50) {
      this.tokenCounterEl.classList.add('warning');
      this.tokenCounterEl.title = `${usagePercent.toFixed(0)}% of ${this.contextWindow.toLocaleString()} context used${providerInfo}`;
    } else {
      this.tokenCounterEl.title = `${usagePercent.toFixed(1)}% of ${this.contextWindow.toLocaleString()} token context${providerInfo}`;
    }
  }

  /**
   * Clear chat history
   */
  clearChat() {
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
