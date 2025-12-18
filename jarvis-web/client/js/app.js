/**
 * Jarvis Web UI - Main Application
 */

class JarvisApp {
  constructor() {
    this.socket = window.jarvisSocket;
    this.chat = window.chatUI;
    
    // UI Elements
    this.statusDot = document.getElementById('statusDot');
    this.statusText = document.getElementById('statusText');
    this.modeSelect = document.getElementById('modeSelect');
    this.audioToggle = document.getElementById('audioToggle');
    this.settingsBtn = document.getElementById('settingsBtn');
    this.settingsModal = document.getElementById('settingsModal');
    this.closeSettings = document.getElementById('closeSettings');
    this.closeSettingsBtn = document.getElementById('closeSettingsBtn');
    this.newChatBtn = document.getElementById('newChatBtn');
    
    // State
    this.audioEnabled = Utils.storage.get('audioEnabled', false);
    
    this._initialize();
  }

  /**
   * Initialize the application
   */
  _initialize() {
    this._setupSocketListeners();
    this._setupUIListeners();
    this._restoreState();
    
    // Connect to server
    this.socket.connect();
    
    // Load conversation history
    this._loadConversationHistory();
    
    console.log('[App] Jarvis Web UI initialized');
  }

  /**
   * Setup socket event listeners
   */
  _setupSocketListeners() {
    this.socket.on('connectionChange', (data) => {
      this._updateConnectionStatus(data.connected);
    });
    
    this.socket.on('sessionReady', (data) => {
      console.log('[App] Session ready:', data);
      this._updateConnectionStatus(true);
      this.statusText.textContent = 'Connected';
      const toolsCount = document.getElementById('toolsCount');
      if (toolsCount) {
        toolsCount.textContent = `${data.tools_count} tools`;
      }
      
      // Sync saved mode with server if different
      const savedMode = Utils.storage.get('mode', data.mode);
      if (savedMode !== data.mode) {
        console.log(`[App] Syncing saved mode (${savedMode}) with server`);
        this.socket.setMode(savedMode);
      }
      
      // Initialize proactive notifications
      if (!this.proactive && window.ProactiveManager) {
        this.proactive = new ProactiveManager(this.socket, this);
        console.log('[App] Proactive notifications enabled');
      }
    });
    
    this.socket.on('connectionError', (data) => {
      Utils.toast(`Connection error: ${data.error}`, 'error');
    });
    
    this.socket.on('modeChanged', async (data) => {
      this.modeSelect.value = data.mode;
      Utils.toast(`Mode changed to ${data.mode}`, 'info');
      
      // Reload settings to reflect new mode's defaults
      if (this.settingsModal.classList.contains('active')) {
        await this._loadSettings();
      }
      
      // Reload tools list
      await this._loadToolsList();
    });
    
    this.socket.on('response', (data) => {
      // Play audio if enabled and available
      if (this.audioEnabled && data.audio_url) {
        this._playAudio(data.audio_url);
      } else if (this.audioEnabled && data.speech) {
        // Generate TTS if no audio_url provided but audio enabled
        this._generateAndPlayTTS(data.speech);
      }
      // Refresh history on new response
      this._loadConversationHistory();
    });
    
    // Handle status updates (progress during long tasks)
    this.socket.on('status', (data) => {
      console.log('[App] Status update:', data.status);
      // Show status in chat as ephemeral message
      this.chat.showStatus(data.status);
      
      // Play TTS for status if audio enabled
      if (this.audioEnabled && data.status) {
        this._generateAndPlayTTS(data.status);
      }
    });
    
    // Handle new conversation created
    this.socket.on('conversationCreated', (data) => {
      console.log('[App] New conversation created:', data);
      this.socket.conversationId = data.conversation_id;
      this._loadConversationHistory();
    });
    
    // Handle conversation loaded
    this.socket.on('conversationLoaded', (data) => {
      console.log('[App] Conversation loaded:', data);
      this._displayLoadedConversation(data.conversation);
    });
  }

  /**
   * Setup UI event listeners
   */
  _setupUIListeners() {
    // Mode selector
    this.modeSelect.addEventListener('change', (e) => {
      const newMode = e.target.value;
      this.socket.setMode(newMode);
      // Suggest refresh for clean state (embeddings, caches, etc. are mode-specific)
      Utils.toast(`Switched to ${newMode} mode. Refresh page for cleanest state.`, 'info', 5000);
    });
    
    // Audio toggle
    this.audioToggle.addEventListener('click', () => {
      this.audioEnabled = !this.audioEnabled;
      Utils.storage.set('audioEnabled', this.audioEnabled);
      this._updateAudioButton();
    });
    
    // Settings modal
    this.settingsBtn.addEventListener('click', () => {
      this.settingsModal.classList.add('active');
      this._loadSettings();
    });
    
    this.closeSettings.addEventListener('click', () => {
      this.settingsModal.classList.remove('active');
    });
    
    this.closeSettingsBtn.addEventListener('click', () => {
      this.settingsModal.classList.remove('active');
    });
    
    // Save settings button
    document.getElementById('saveSettingsBtn')?.addEventListener('click', () => {
      this._saveSettings();
    });
    
    // Settings tabs
    document.querySelectorAll('.settings-tab').forEach(tab => {
      tab.addEventListener('click', () => {
        const tabName = tab.dataset.settingsTab;
        
        // Update active tab
        document.querySelectorAll('.settings-tab').forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        
        // Update active panel
        document.querySelectorAll('.settings-panel').forEach(p => p.classList.remove('active'));
        document.getElementById(`settings-${tabName}`)?.classList.add('active');
        
        // Load tools tab content
        if (tabName === 'tools') {
          this._loadBlockedTools();
        }
      });
    });
    
    
    // LLM Provider change → update model dropdown
    document.getElementById('setting-llm-provider')?.addEventListener('change', (e) => {
      const provider = e.target.value || this._settingsData?.llm?.provider?.default || 'xai';
      this._populateModelDropdown(provider);
      document.getElementById('setting-llm-model').value = '';  // Reset model selection
    });
    
    // Reset to defaults button
    document.getElementById('resetDefaultsBtn')?.addEventListener('click', () => {
      this._resetToDefaults();
    });
    
    // Add blocked tool button
    document.getElementById('addBlockedToolBtn')?.addEventListener('click', () => {
      this._addBlockedTool();
    });
    
    // Close modal on outside click
    this.settingsModal.addEventListener('click', (e) => {
      if (e.target === this.settingsModal) {
        this.settingsModal.classList.remove('active');
      }
    });
    
    // New chat button
    this.newChatBtn.addEventListener('click', () => {
      this._startNewChat();
    });
    
    // Sidebar tabs
    document.querySelectorAll('.sidebar-tab').forEach(tab => {
      tab.addEventListener('click', () => {
        const tabName = tab.dataset.tab;
        
        // Update active tab
        document.querySelectorAll('.sidebar-tab').forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        
        // Update active content
        document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
        document.getElementById(`tab-${tabName}`).classList.add('active');
        
        // Load tools if switching to tools tab
        if (tabName === 'tools') {
          this._loadToolsList();
        }
        // Load history if switching to conversations tab
        if (tabName === 'conversations') {
          this._loadConversationHistory();
        }
      });
    });
    
    // Keyboard shortcuts
    document.addEventListener('keydown', (e) => {
      // Escape to close modal
      if (e.key === 'Escape' && this.settingsModal.classList.contains('active')) {
        this.settingsModal.classList.remove('active');
      }
      
      // Ctrl/Cmd + / to focus input
      if ((e.ctrlKey || e.metaKey) && e.key === '/') {
        e.preventDefault();
        document.getElementById('chatInput').focus();
      }
    });
  }

  /**
   * Restore saved state
   */
  _restoreState() {
    // Restore mode
    const savedMode = Utils.storage.get('mode', 'cloud');
    this.modeSelect.value = savedMode;
    this.socket.mode = savedMode;
    
    // Update audio button
    this._updateAudioButton();
  }

  /**
   * Update connection status UI
   */
  _updateConnectionStatus(connected) {
    if (connected) {
      this.statusDot.classList.add('connected');
      this.statusText.textContent = 'Connected';
    } else {
      this.statusDot.classList.remove('connected');
      this.statusText.textContent = 'Disconnected';
    }
  }

  /**
   * Update audio toggle button
   */
  _updateAudioButton() {
    this.audioToggle.textContent = this.audioEnabled ? '🔊' : '🔇';
    this.audioToggle.classList.toggle('active', this.audioEnabled);
  }

  /**
   * Play audio response
   */
  _playAudio(url) {
    console.log('[App] Playing audio:', url);
    const audio = new Audio(url);
    audio.play().catch(err => {
      console.warn('[App] Audio playback failed:', err);
      Utils.toast('Audio playback failed', 'error');
    });
  }
  
  /**
   * Generate TTS and play audio
   */
  async _generateAndPlayTTS(text) {
    if (!text || text.length > 1000) {
      // Skip very long text
      console.log('[App] Skipping TTS for text length:', text?.length);
      return;
    }
    
    try {
      console.log('[App] Generating TTS for:', text.substring(0, 50) + '...', 'mode:', this.socket.mode);
      
      const response = await fetch('/api/tts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, mode: this.socket.mode })
      });
      
      if (response.ok) {
        const contentType = response.headers.get('Content-Type');
        console.log('[App] TTS response Content-Type:', contentType);
        const blob = await response.blob();
        console.log('[App] TTS blob size:', blob.size, 'type:', blob.type);
        if (blob.size > 0) {
          const audioUrl = URL.createObjectURL(blob);
          this._playAudio(audioUrl);
        } else {
          console.warn('[App] TTS returned empty audio');
        }
      } else {
        const errorText = await response.text();
        console.warn('[App] TTS generation failed:', response.status, errorText);
      }
    } catch (err) {
      console.error('[App] TTS error:', err);
    }
  }

  /**
   * Load and display tools list
   */
  async _loadToolsList() {
    const container = document.getElementById('toolsList');
    
    try {
      const response = await fetch('/api/tools?summary=true');
      const data = await response.json();
      
      if (data.ok && data.tools) {
        const tools = data.tools;
        const stats = data.stats || {};
        
        // Show stats header
        let html = `
          <div class="tools-stats">
            <span title="Local tools">📁 ${stats.local || 0}</span>
            <span title="MCP tools">🔌 ${stats.mcp || 0}</span>
            <span title="Blocked for web">🚫 ${stats.blocked || 0}</span>
          </div>
        `;
        
        // Group tools
        const localTools = tools.filter(t => t.source === 'local' && !t.blocked);
        const mcpTools = tools.filter(t => t.source === 'mcp' && !t.blocked);
        const blockedTools = tools.filter(t => t.blocked);
        
        // Local tools section
        if (localTools.length > 0) {
          html += '<div class="tools-section-header">📁 Local Tools</div>';
          for (const tool of localTools) {
            html += this._renderToolItem(tool);
          }
        }
        
        // MCP tools section
        if (mcpTools.length > 0) {
          html += '<div class="tools-section-header">🔌 MCP Tools</div>';
          for (const tool of mcpTools) {
            html += this._renderToolItem(tool);
          }
        }
        
        // Blocked tools section
        if (blockedTools.length > 0) {
          html += '<div class="tools-section-header">🚫 Blocked (Web Only)</div>';
          for (const tool of blockedTools) {
            html += this._renderToolItem(tool);
          }
        }
        
        container.innerHTML = html || '<p style="color: var(--text-muted); padding: var(--space-md);">No tools loaded</p>';
      } else {
        container.innerHTML = '<p style="color: var(--error); padding: var(--space-md);">Failed to load tools</p>';
      }
    } catch (err) {
      container.innerHTML = `<p style="color: var(--error); padding: var(--space-md);">Error: ${err.message}</p>`;
    }
  }
  
  /**
   * Render a single tool item
   */
  _renderToolItem(tool) {
    const emoji = this._getToolEmoji(tool.name);
    const desc = (tool.description || '').replace(/[📞🎵🖼️⚡🔧💾📄✉️🖨️🔔⏰💡🌐🔍💬📝🧠💰🎤]/g, '').trim();
    const isBlocked = tool.blocked;
    const isMcp = tool.source === 'mcp';
    
    const classes = ['tool-item'];
    if (isBlocked) classes.push('tool-blocked');
    if (isMcp) classes.push('tool-mcp');
    
    const badge = isBlocked ? '<span class="tool-badge blocked">blocked</span>' : 
                  isMcp ? '<span class="tool-badge mcp">mcp</span>' : '';
    
    return `
      <div class="${classes.join(' ')}" title="${Utils.escapeHtml(tool.description || tool.name)}">
        <div class="tool-item-name">${emoji} ${Utils.escapeHtml(tool.name)} ${badge}</div>
        <div class="tool-item-desc">${Utils.escapeHtml(Utils.truncate(desc, 50))}</div>
      </div>
    `;
  }
  
  /**
   * Get emoji for tool based on name
   */
  _getToolEmoji(name) {
    const emojiMap = {
      'phone_call': '📞',
      'spotify': '🎵',
      'generate_image': '🖼️',
      'send_email': '✉️',
      'printer': '🖨️',
      'weather': '🌤️',
      'remember': '💾',
      'recall': '🧠',
      'search_memory': '🔍',
      'semantic_recall': '🔍',
      'canvas': '📝',
      'stash': '📦',
      'pdf_create': '📄',
      'crypto_price': '💰',
      'opencode': '💻',
      'list_reminders': '⏰',
      'set_reminder': '⏰',
      'system_monitor': '📊',
      'network_tools': '🌐',
      'speaker_volume': '🔊',
    };
    return emojiMap[name] || '🔧';
  }

  /**
   * Load and display settings
   */
  async _loadSettings() {
    try {
      const response = await fetch('/api/settings');
      const data = await response.json();
      
      if (data.ok && data.settings) {
        const s = data.settings;
        this._settingsData = s;  // Cache for later use
        
        // Populate General settings
        document.getElementById('setting-mode').value = s.mode || 'cloud';
        document.getElementById('setting-tts').checked = s.audio?.tts_enabled || false;
        
        // Populate LLM Provider
        const providerSelect = document.getElementById('setting-llm-provider');
        providerSelect.value = s.llm?.provider?.is_override ? s.llm.provider.value : '';
        const providerDefault = document.getElementById('llm-provider-default');
        const envFile = s.mode === 'local' ? 'local.env' : 'cloud.env';
        providerDefault.textContent = `(${envFile}: ${s.llm?.provider?.default || 'xai'})`;
        providerDefault.className = s.llm?.provider?.is_override ? 'setting-default setting-override' : 'setting-default';
        if (s.llm?.provider?.is_override) {
          providerDefault.textContent = `⚡ override: ${s.llm.provider.value}`;
        }
        
        // Populate LLM Model dropdown based on provider
        this._populateModelDropdown(s.llm?.provider?.value || s.llm?.provider?.default || 'xai');
        const modelSelect = document.getElementById('setting-llm-model');
        modelSelect.value = s.llm?.model?.is_override ? s.llm.model.value : '';
        const modelDefault = document.getElementById('llm-model-default');
        modelDefault.textContent = `(${envFile}: ${s.llm?.model?.default || 'default'})`;
        modelDefault.className = s.llm?.model?.is_override ? 'setting-default setting-override' : 'setting-default';
        if (s.llm?.model?.is_override) {
          modelDefault.textContent = `⚡ override: ${s.llm.model.value}`;
        }
        
        // Populate Image Provider
        const imageSelect = document.getElementById('setting-image-provider');
        imageSelect.value = s.image?.provider?.is_override ? s.image.provider.value : '';
        const imageDefault = document.getElementById('image-provider-default');
        imageDefault.textContent = `(${envFile}: ${s.image?.provider?.default || 'gemini'})`;
        imageDefault.className = s.image?.provider?.is_override ? 'setting-default setting-override' : 'setting-default';
        if (s.image?.provider?.is_override) {
          imageDefault.textContent = `⚡ override: ${s.image.provider.value}`;
        }
        
        // Populate Conversation History Limit
        const historyLimit = s.conversation?.history_limit || 20;
        document.getElementById('setting-history-limit').value = historyLimit;
        
        // Populate API Keys status
        const apiKeysContainer = document.getElementById('api-keys-status');
        const apiKeys = s.api_keys || {};
        
        let apiHtml = '';
        for (const [key, configured] of Object.entries(apiKeys)) {
          apiHtml += `
            <div class="api-key-item">
              <span class="api-key-name">${key}</span>
              <span class="api-key-status ${configured ? 'configured' : 'missing'}">
                ${configured ? '✓ Configured' : '✗ Not set'}
              </span>
            </div>
          `;
        }
        apiKeysContainer.innerHTML = apiHtml;
      }
      
      // Load system config (read-only values from cloud.env)
      await this._loadSystemConfig();
      
    } catch (err) {
      console.error('[App] Failed to load settings:', err);
      Utils.toast(`Failed to load settings: ${err.message}`, 'error');
    }
  }
  
  /**
   * Load system config (read-only values from current mode's env)
   */
  async _loadSystemConfig() {
    try {
      const response = await fetch(`/api/settings/system?mode=${this.socket.mode}`);
      const data = await response.json();
      
      if (data.ok && data.config) {
        const container = document.getElementById('system-config');
        const c = data.config;
        const isLocal = data.mode === 'local';
        
        // Mode-specific model display
        const modelHtml = isLocal ? `
          <div class="config-item">
            <span class="config-label">OLLAMA_MODEL</span>
            <span class="config-value">${c.OLLAMA_MODEL || '(not set)'}</span>
          </div>
          <div class="config-item">
            <span class="config-label">OLLAMA_BASE_URL</span>
            <span class="config-value">${c.OLLAMA_BASE_URL || '(not set)'}</span>
          </div>
        ` : `
          <div class="config-item">
            <span class="config-label">XAI_MODEL</span>
            <span class="config-value">${c.XAI_MODEL || '(not set)'}</span>
          </div>
          <div class="config-item">
            <span class="config-label">ANTHROPIC_MODEL</span>
            <span class="config-value">${c.ANTHROPIC_MODEL || '(not set)'}</span>
          </div>
          <div class="config-item">
            <span class="config-label">OPENAI_MODEL</span>
            <span class="config-value">${c.OPENAI_MODEL || '(not set)'}</span>
          </div>
        `;
        
        container.innerHTML = `
          <div class="config-section-title">🧠 LLM Settings (${isLocal ? 'local.env' : 'cloud.env'})</div>
          <div class="config-item">
            <span class="config-label">LLM_PROVIDER</span>
            <span class="config-value">${c.LLM_PROVIDER}</span>
          </div>
          ${modelHtml}
          
          <div class="config-section">
            <div class="config-section-title">🎯 Thresholds</div>
            <div class="config-item">
              <span class="config-label">TOOL_SIMILARITY_THRESHOLD</span>
              <span class="config-value">${c.TOOL_SIMILARITY_THRESHOLD}</span>
            </div>
            <div class="config-item">
              <span class="config-label">SEMANTIC_SIMILARITY_THRESHOLD</span>
              <span class="config-value">${c.SEMANTIC_SIMILARITY_THRESHOLD}</span>
            </div>
          </div>
          
          <div class="config-section">
            <div class="config-section-title">🔊 Audio (${isLocal ? 'Kokoro' : 'ElevenLabs'})</div>
            <div class="config-item">
              <span class="config-label">TTS_PROVIDER</span>
              <span class="config-value">${c.TTS_PROVIDER}</span>
            </div>
            ${isLocal ? `
            <div class="config-item">
              <span class="config-label">TTS_URL</span>
              <span class="config-value">${c.TTS_URL || '(not set)'}</span>
            </div>
            <div class="config-item">
              <span class="config-label">TTS_VOICE</span>
              <span class="config-value">${c.TTS_VOICE || '(default)'}</span>
            </div>
            ` : `
            <div class="config-item">
              <span class="config-label">ELEVENLABS_TTS_VOICE</span>
              <span class="config-value">${c.ELEVENLABS_TTS_VOICE || '(default)'}</span>
            </div>
            `}
            <div class="config-item">
              <span class="config-label">STATUS_UPDATES_ENABLED</span>
              <span class="config-value ${c.STATUS_UPDATES_ENABLED === 'true' ? 'enabled' : 'disabled'}">${c.STATUS_UPDATES_ENABLED}</span>
            </div>
          </div>
          
          <div class="config-section">
            <div class="config-section-title">⚡ Features</div>
            <div class="config-item">
              <span class="config-label">JARVIS_INTELLIGENCE</span>
              <span class="config-value ${c.JARVIS_INTELLIGENCE === 'true' ? 'enabled' : 'disabled'}">${c.JARVIS_INTELLIGENCE}</span>
            </div>
            <div class="config-item">
              <span class="config-label">IMAGE_TOOL_PROVIDER</span>
              <span class="config-value">${c.IMAGE_TOOL_PROVIDER}</span>
            </div>
          </div>
          
          <div class="config-section">
            <div class="config-section-title">🌍 System</div>
            <div class="config-item">
              <span class="config-label">JARVIS_TIMEZONE</span>
              <span class="config-value">${c.JARVIS_TIMEZONE}</span>
            </div>
            <div class="config-item">
              <span class="config-label">Mode</span>
              <span class="config-value">${data.mode}</span>
            </div>
          </div>
        `;
      }
    } catch (err) {
      console.error('[App] Failed to load system config:', err);
    }
  }
  
  /**
   * Populate model dropdown based on selected provider
   */
  _populateModelDropdown(provider) {
    const modelSelect = document.getElementById('setting-llm-model');
    const models = this._settingsData?.provider_models?.[provider] || [];
    
    let html = '<option value="">Use default for provider</option>';
    for (const model of models) {
      html += `<option value="${model.id}">${model.name} (${model.context})</option>`;
    }
    modelSelect.innerHTML = html;
  }
  
  /**
   * Start a new chat
   */
  _startNewChat() {
    this.socket.conversationId = null;
    this.chat.clearChat();
    this._updateActiveConversation(null);
    Utils.toast('Started new chat', 'info');
  }
  
  /**
   * Load conversation history
   */
  async _loadConversationHistory() {
    const container = document.getElementById('historyList');
    
    try {
      const response = await fetch('/api/conversations?limit=30');
      const data = await response.json();
      
      if (data.ok && data.conversations) {
        const convs = data.conversations;
        
        if (convs.length === 0) {
          container.innerHTML = `
            <div class="history-empty">
              <div class="history-empty-icon">💬</div>
              <div>No conversations yet</div>
              <div style="margin-top: var(--space-sm); font-size: var(--text-xs);">Start chatting to save history</div>
            </div>
          `;
          return;
        }
        
        let html = '';
        for (const conv of convs) {
          const isActive = this.socket.conversationId === conv.id;
          const date = this._formatRelativeDate(conv.updated_at);
          
          html += `
            <div class="history-item ${isActive ? 'active' : ''}" 
                 data-conv-id="${conv.id}"
                 onclick="window.jarvisApp.loadConversation('${conv.id}')">
              <div class="history-item-content">
                <div class="history-title">${Utils.escapeHtml(conv.title || 'Untitled')}</div>
                <div class="history-date">${date} · ${conv.message_count || 0} messages</div>
              </div>
              <button class="history-delete" 
                      onclick="event.stopPropagation(); window.jarvisApp.deleteConversation('${conv.id}')"
                      title="Delete conversation">🗑️</button>
            </div>
          `;
        }
        
        container.innerHTML = html;
      } else {
        container.innerHTML = '<div class="history-empty">Failed to load history</div>';
      }
    } catch (err) {
      console.error('[App] Failed to load history:', err);
      container.innerHTML = `<div class="history-empty">Error: ${err.message}</div>`;
    }
  }
  
  /**
   * Load a specific conversation
   */
  loadConversation(convId) {
    console.log('[App] Loading conversation:', convId);
    this.socket.emit('conversation:load', { conversation_id: convId });
  }
  
  /**
   * Delete a conversation
   */
  async deleteConversation(convId) {
    if (!confirm('Delete this conversation?')) return;
    
    try {
      const response = await fetch(`/api/conversations/${convId}`, {
        method: 'DELETE'
      });
      const data = await response.json();
      
      if (data.ok) {
        // If we deleted the current conversation, clear the chat
        if (this.socket.conversationId === convId) {
          this._startNewChat();
        }
        this._loadConversationHistory();
        Utils.toast('Conversation deleted', 'info');
      } else {
        Utils.toast('Failed to delete conversation', 'error');
      }
    } catch (err) {
      Utils.toast(`Error: ${err.message}`, 'error');
    }
  }
  
  /**
   * Display a loaded conversation in the chat
   */
  _displayLoadedConversation(conversation) {
    if (!conversation) return;
    
    // Update socket's conversation ID
    this.socket.conversationId = conversation.id;
    this._updateActiveConversation(conversation.id);
    
    // Clear and rebuild chat
    this.chat.clearChat();
    
    // Add each message
    for (const msg of conversation.messages || []) {
      if (msg.role === 'user') {
        this.chat.addUserMessage(msg.content);
      } else if (msg.role === 'assistant') {
        // Pass as separate parameters: text, toolsUsed, data
        this.chat.addAssistantMessage(
          msg.content || '',
          msg.tools_used || [],
          msg.data || {}
        );
      }
    }
    
    // Update history UI
    this._loadConversationHistory();
  }
  
  /**
   * Update active conversation in sidebar
   */
  _updateActiveConversation(convId) {
    document.querySelectorAll('.history-item').forEach(item => {
      if (item.dataset.convId === convId) {
        item.classList.add('active');
      } else {
        item.classList.remove('active');
      }
    });
  }
  
  /**
   * Format relative date
   */
  _formatRelativeDate(isoDate) {
    if (!isoDate) return '';
    
    const date = new Date(isoDate);
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);
    
    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    if (diffDays < 7) return `${diffDays}d ago`;
    
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  }
  
  /**
   * Save settings
   */
  async _saveSettings() {
    try {
      // Collect all settings
      const settings = {
        tts_enabled: document.getElementById('setting-tts').checked,
        llm_provider: document.getElementById('setting-llm-provider').value || null,
        llm_model: document.getElementById('setting-llm-model').value || null,
        image_provider: document.getElementById('setting-image-provider').value || null,
        history_limit: parseInt(document.getElementById('setting-history-limit').value) || 20
      };
      
      // Save to server
      const response = await fetch('/api/settings/web', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(settings)
      });
      
      const result = await response.json();
      
      if (result.ok) {
        // Update mode if changed
        const newMode = document.getElementById('setting-mode').value;
        if (newMode !== this.socket.mode) {
          this.socket.setMode(newMode);
          this.modeSelect.value = newMode;
        }
        
        // Update audio setting
        this.audioEnabled = document.getElementById('setting-tts').checked;
        Utils.storage.set('audioEnabled', this.audioEnabled);
        this._updateAudioButton();
        
        Utils.toast('Settings saved!', 'success');
        this.settingsModal.classList.remove('active');
      } else {
        Utils.toast('Failed to save settings', 'error');
      }
    } catch (err) {
      Utils.toast(`Error: ${err.message}`, 'error');
    }
  }
  
  /**
   * Reset settings to cloud.env defaults
   */
  async _resetToDefaults() {
    if (!confirm('Reset all web overrides to cloud.env defaults?')) return;
    
    try {
      const response = await fetch('/api/settings/reset', { method: 'POST' });
      const result = await response.json();
      
      if (result.ok) {
        Utils.toast('Reset to defaults!', 'success');
        this._loadSettings();  // Reload to show defaults
      } else {
        Utils.toast('Failed to reset', 'error');
      }
    } catch (err) {
      Utils.toast(`Error: ${err.message}`, 'error');
    }
  }
  
  /**
   * Load blocked tools into settings panel
   */
  async _loadBlockedTools() {
    try {
      // Get current blocked tools
      const blockedResponse = await fetch('/api/settings/blocked-tools');
      const blockedData = await blockedResponse.json();
      const blocked = blockedData.blocked || [];
      
      // Get all tools for dropdown
      const toolsResponse = await fetch('/api/tools?summary=true');
      const toolsData = await toolsResponse.json();
      const allTools = toolsData.tools || [];
      
      // Render blocked tools chips
      const listContainer = document.getElementById('blocked-tools-list');
      if (blocked.length === 0) {
        listContainer.innerHTML = '<span class="blocked-tools-empty">No tools blocked</span>';
      } else {
        listContainer.innerHTML = blocked.map(tool => `
          <span class="blocked-tool-chip">
            ${Utils.escapeHtml(tool)}
            <button class="remove-btn" data-tool="${Utils.escapeHtml(tool)}" title="Unblock">×</button>
          </span>
        `).join('');
        
        // Add click handlers to remove buttons
        listContainer.querySelectorAll('.remove-btn').forEach(btn => {
          btn.addEventListener('click', () => this._removeBlockedTool(btn.dataset.tool));
        });
      }
      
      // Populate dropdown with non-blocked tools
      const select = document.getElementById('block-tool-select');
      const availableTools = allTools.filter(t => !blocked.includes(t.name));
      select.innerHTML = '<option value="">Select a tool...</option>' + 
        availableTools.map(t => `<option value="${Utils.escapeHtml(t.name)}">${Utils.escapeHtml(t.name)}</option>`).join('');
        
    } catch (err) {
      console.error('[App] Failed to load blocked tools:', err);
    }
  }
  
  /**
   * Add a tool to blocked list
   */
  async _addBlockedTool() {
    const select = document.getElementById('block-tool-select');
    const toolName = select.value;
    
    if (!toolName) {
      Utils.toast('Select a tool first', 'warning');
      return;
    }
    
    try {
      // Get current blocked
      const response = await fetch('/api/settings/blocked-tools');
      const data = await response.json();
      const blocked = data.blocked || [];
      
      if (!blocked.includes(toolName)) {
        blocked.push(toolName);
        
        // Save
        await fetch('/api/settings/blocked-tools', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ blocked })
        });
        
        Utils.toast(`Blocked: ${toolName}`, 'success');
        this._loadBlockedTools();
        this._loadToolsList();  // Refresh tools list
      }
    } catch (err) {
      Utils.toast(`Error: ${err.message}`, 'error');
    }
  }
  
  /**
   * Remove a tool from blocked list
   */
  async _removeBlockedTool(toolName) {
    try {
      const response = await fetch('/api/settings/blocked-tools');
      const data = await response.json();
      let blocked = data.blocked || [];
      
      blocked = blocked.filter(t => t !== toolName);
      
      await fetch('/api/settings/blocked-tools', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ blocked })
      });
      
      Utils.toast(`Unblocked: ${toolName}`, 'success');
      this._loadBlockedTools();
      this._loadToolsList();  // Refresh tools list
    } catch (err) {
      Utils.toast(`Error: ${err.message}`, 'error');
    }
  }
}


// Initialize app when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
  window.jarvisApp = new JarvisApp();
});

