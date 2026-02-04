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
          const triggerName = trigger.replace('/', '');
          if (triggerName.toLowerCase().startsWith(query) || query === '') {
            suggestions.push({
              type: 'workflow',
              name: triggerName,
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
    
    // Check for /workflow
    const cmdMatch = input.match(/^\/(\w+[-\w]*)\s*(.*)/s);
    if (cmdMatch) {
      const cmdName = cmdMatch[1].toLowerCase();
      
      // Check if it's a workflow trigger
      for (const [id, wf] of Object.entries(this.workflows || {})) {
        const triggers = wf.triggers || [];
        for (const trigger of triggers) {
          if (trigger.replace('/', '') === cmdName) {
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
      parts.push(`/${parsed.workflow} ${wf?.icon || '🔄'}`);
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
    
    // Image upload elements
    this.uploadBtn = document.getElementById('uploadBtn');
    this.imageInput = document.getElementById('imageInput');
    this.imagePreviewContainer = document.getElementById('imagePreviewContainer');
    this.imagePreview = document.getElementById('imagePreview');
    this.removeImageBtn = document.getElementById('removeImageBtn');
    
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
    if (input.startsWith('/') || input.startsWith('@')) {
      Utils.toast('Remove the / or @ prefix first to enhance', 'info');
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
      
      return `
        <div class="autocomplete-item" data-index="${i}" data-type="${s.type}" data-name="${s.name}">
          <span class="autocomplete-icon">${s.icon}</span>
          <span class="autocomplete-name">${s.type === 'prompt' ? '@' : '/'}${s.name}</span>
          <span class="autocomplete-desc">${Utils.truncate(s.description, 85)}</span>
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
        // Position tooltip for workflow and prompt items
        const tooltip = item.querySelector('.workflow-tooltip, .prompt-tooltip');
        if (tooltip) {
          const rect = item.getBoundingClientRect();
          tooltip.style.display = 'block';
          tooltip.style.left = `${rect.right + 8}px`;
          tooltip.style.top = `${rect.top}px`;
          // Keep tooltip on screen
          const tooltipRect = tooltip.getBoundingClientRect();
          if (tooltipRect.right > window.innerWidth) {
            tooltip.style.left = `${rect.left - tooltipRect.width - 8}px`;
          }
          if (tooltipRect.bottom > window.innerHeight) {
            tooltip.style.top = `${window.innerHeight - tooltipRect.height - 8}px`;
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
    const prefix = type === 'prompt' ? '@' : '/';
    
    // Replace entire input with selected workflow/prompt + space
    this.inputField.value = `${prefix}${name} `;
    
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
      this.isProcessing = false;
      this.updateSendButton();
      
      // Update token counter if usage data available
      if (data.usage) {
        this._updateTokenCounter(data.usage);
      }
      
      // Show discrete toast for server-side tools (xAI/Anthropic native search)
      if (data.server_side_tools && Object.keys(data.server_side_tools).length > 0) {
        const tools = Object.entries(data.server_side_tools)
          .map(([name, count]) => {
            // Clean up tool name: SERVER_SIDE_TOOL_X_SEARCH -> x search
            const cleanName = name.replace('SERVER_SIDE_TOOL_', '').toLowerCase().replace(/_/g, ' ');
            return `${cleanName}${count > 1 ? ` (${count}x)` : ''}`;
          })
          .join(', ');
        Utils.toast(`🔍 Provider: ${tools}`, 'info', 4000);
      }
    });
    
    socket.on('error', (data) => {
      this.hideThinking();
      this.addErrorMessage(data.error);
      this.isProcessing = false;
      this.updateSendButton();
    });
    
    // Feedback events (async analysis after response)
    socket.on('feedbackStart', (data) => {
      this.pendingFeedback = { message_id: data.message_id, status: 'analyzing' };
      this._showFeedbackCard('analyzing');
    });
    
    socket.on('feedbackComplete', (data) => {
      this.pendingFeedback = null;
      this._updateFeedbackCard(data);
    });
  }

  /**
   * Setup image upload functionality
   */
  _setupImageUpload() {
    if (!this.uploadBtn || !this.imageInput) {
      console.warn('[Chat] Image upload elements not found');
      return;
    }
    
    // Click upload button -> trigger file input
    this.uploadBtn.addEventListener('click', () => {
      this.imageInput.click();
    });
    
    // Handle file selection
    this.imageInput.addEventListener('change', async (e) => {
      const file = e.target.files[0];
      if (file) {
        await this.attachImage(file);
      }
      // Reset input so same file can be selected again
      this.imageInput.value = '';
    });
    
    // Remove image button
    if (this.removeImageBtn) {
      this.removeImageBtn.addEventListener('click', () => {
        this.clearAttachedImage();
      });
    }
    
    // Drag and drop support
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
        if (file && file.type.startsWith('image/')) {
          await this.attachImage(file);
        }
      });
    }
    
    // Paste image from clipboard
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
    
    console.log('[Chat] Image upload ready');
  }
  
  /**
   * Attach an image file (upload to server)
   */
  async attachImage(file) {
    // Validate file type
    if (!file.type.startsWith('image/')) {
      Utils.toast('Please select an image file', 'error');
      return;
    }
    
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
        this.attachedImage = {
          base64: data.base64,
          url: data.url,
          filename: data.filename
        };
        
        // Show preview
        this.showImagePreview(data.url);
        Utils.toast(`Image attached (${data.size_kb}KB)`, 'success', 1500);
        
        // Focus input for typing question
        this.inputField.focus();
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
    }
    if (this.imagePreview) {
      this.imagePreview.src = '';
    }
  }

  /**
   * Send a message (with optional attached image)
   */
  sendMessage() {
    let rawMessage = this.inputField.value.trim();
    const hasImage = this.attachedImage !== null;
    
    // Need either message or image
    if (!rawMessage && !hasImage) return;
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
    }, requestFeedback);
    
    // Clear attached image after sending
    this.clearAttachedImage();
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
    
    // Remove new-message class after animation completes (2.5s)
    setTimeout(() => {
      messageEl.classList.remove('new-message');
    }, 2500);
    
    // Build tool cards HTML from pendingTools (supports duplicate tools with unique keys)
    const toolResultsData = data.data || data || {};
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
    
    const parsedText = Utils.parseMarkdown(text);
    
    // Build expandable details section
    // raw_llm_response is inside data.data (nested), also check top level for loaded conversations
    let detailsHtml = '';
    const innerData = data.data || data || {};
    const rawResponse = innerData.raw_llm_response || innerData.vision_analysis || data.raw_llm_response || data.vision_analysis || '';
    const hasDetails = rawResponse && rawResponse !== text && rawResponse.length > text.length;
    
    if (hasDetails) {
      const detailsContent = Utils.escapeHtml(rawResponse);
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
    
    this.messagesContainer.appendChild(messageEl);
    Utils.scrollToBottom(this.messagesContainer);
    
    // Clear pending tools
    this.pendingTools = {};
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
      bodyEl.textContent = typeof result === 'object' 
        ? Utils.formatJson(result) 
        : String(result);
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
        <pre class="tool-card-body">${Utils.escapeHtml(summary)}</pre>
      </div>
    `;
  }

  /**
   * Show feedback card in analyzing state
   */
  _showFeedbackCard(status = 'analyzing') {
    // Remove existing feedback card if any
    const existingCard = document.getElementById('feedback-card');
    if (existingCard) {
      existingCard.remove();
    }
    
    // Find the last assistant message to append feedback to
    const messages = this.messagesContainer.querySelectorAll('.message.assistant:not(.thinking-message)');
    const lastMessage = messages[messages.length - 1];
    
    if (!lastMessage) {
      return;
    }
    
    const cardHtml = `<div id="feedback-card" class="tool-card feedback pending expanded" style="margin-top: 12px;">
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
    const card = document.getElementById('feedback-card');
    if (!card) {
      // Card doesn't exist, create it and retry
      this._showFeedbackCard();
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
    if (!this.isProcessing) return;
    
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

