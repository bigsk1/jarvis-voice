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
    
    // Audio playback control elements
    this.speakerBtn = document.getElementById('speakerBtn');
    
    // Conversation ID badge
    this.convIdBadge = document.getElementById('convIdBadge');
    this.convIdText = document.getElementById('convIdText');
    
    // State
    this.audioEnabled = Utils.storage.get('audioEnabled', false);
    this.glowIntensity = Utils.storage.get('glowIntensity', 'low');
    this._settingsData = null;
    this._conversations = [];
    this._archivedExpanded = false;
    
    // Audio playback state
    this.currentAudio = null;
    this.isPlaying = false;
    this.audioQueue = [];  // Queue for multiple audio clips
    
    this._initialize();
  }

  /**
   * Initialize the application
   */
  _initialize() {
    this._setupSocketListeners();
    this._setupUIListeners();
    this._restoreState();
    this._applyGlowIntensity();  // Apply saved glow intensity
    this._updateSpeakerButton(); // Ensure speaker button is hidden initially
    
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

      // Rejoin the active conversation room after socket reconnects so
      // in-flight responses continue streaming to the browser.
      if (this.socket.conversationId) {
        console.log('[App] Rejoining active conversation after reconnect:', this.socket.conversationId);
        this.socket.emit('conversation:load', {
          conversation_id: this.socket.conversationId,
          reconnect_only: true
        });
      }
      
      // Initialize proactive notifications
      if (!this.proactive && window.ProactiveManager) {
        this.proactive = new ProactiveManager(this.socket, this);
        console.log('[App] Proactive notifications enabled');
      }
      
      // Initialize log panel
      if (!this.logPanel && window.LogPanelManager) {
        this.logPanel = new LogPanelManager(this.socket.socket);
        console.log('[App] Log panel enabled');
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
      await window.commandSystem?.refreshTools?.();
      
      // Update token counter context window for new mode
      if (window.chatUI) {
        await window.chatUI.refreshContextWindow(data.mode);
      }
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
      this._updateConvIdBadge(data.conversation_id);
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
    // Hamburger menu (mobile sidebar toggle)
    const hamburgerBtn = document.getElementById('hamburgerBtn');
    const sidebar = document.getElementById('sidebar');
    const sidebarOverlay = document.getElementById('sidebarOverlay');
    
    if (hamburgerBtn && sidebar) {
      hamburgerBtn.addEventListener('click', () => {
        sidebar.classList.toggle('mobile-open');
        document.body.classList.toggle('sidebar-open');
      });
      
      // Close sidebar when clicking overlay
      if (sidebarOverlay) {
        sidebarOverlay.addEventListener('click', () => {
          sidebar.classList.remove('mobile-open');
          document.body.classList.remove('sidebar-open');
        });
      }
      
      // Close sidebar when clicking a conversation (mobile UX)
      sidebar.addEventListener('click', (e) => {
        if (e.target.closest('.history-item') && window.innerWidth <= 768) {
          sidebar.classList.remove('mobile-open');
          document.body.classList.remove('sidebar-open');
        }
      });
    }
    
    // Mode selector
    this.modeSelect.addEventListener('change', async (e) => {
      const newMode = e.target.value;
      this.socket.setMode(newMode);
      window.chatUI?._handleImageAttachmentsForMode?.(newMode, { toast: false });
      // Suggest refresh for clean state (embeddings, caches, etc. are mode-specific)
      Utils.toast(`Switched to ${newMode} mode. Refresh page for cleanest state.`, 'info', 5000);
      
      // Update token counter context window for new mode
      if (window.chatUI) {
        await window.chatUI.refreshContextWindow(newMode);
      }
    });
    
    // Audio toggle (enable/disable TTS)
    this.audioToggle.addEventListener('click', async () => {
      this.audioEnabled = !this.audioEnabled;
      Utils.storage.set('audioEnabled', this.audioEnabled);
      this._updateAudioButton();
      
      // If disabling audio, also stop any current playback
      if (!this.audioEnabled && this.currentAudio) {
        this.stopAudioPlayback();
      }
      
      const settingsPayload = { tts_enabled: this.audioEnabled };
      if (this.audioEnabled) {
        const effectiveStyle = await this._getEffectiveResponseStyle();
        if (effectiveStyle === 'detailed') {
          settingsPayload.response_style = 'auto';
        }
      }

      // Sync to server so TTS generation is actually disabled (saves 11labs tokens!)
      try {
        await fetch('/api/settings/web', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(settingsPayload)
        });
        this._applyLocalSettingsUpdate(settingsPayload);
        if (settingsPayload.response_style === 'auto') {
          Utils.toast('TTS enabled. Response style switched from detailed to auto for speech-friendly answers.', 'info', 3500);
        }
      } catch (err) {
        console.error('Failed to sync TTS setting to server:', err);
      }
    });
    
    // Speaker button (pause/resume playback)
    if (this.speakerBtn) {
      this.speakerBtn.addEventListener('click', () => {
        this.toggleAudioPlayback();
      });
      
      // Double-click to stop completely
      this.speakerBtn.addEventListener('dblclick', () => {
        this.stopAudioPlayback();
        Utils.toast('Audio stopped', 'info', 1500);
      });
    }
    
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
    document.getElementById('setting-llm-provider')?.addEventListener('change', async (e) => {
      const provider = e.target.value || this._settingsData?.llm?.provider?.default || 'xai';
      await this._ensureProviderModelsLoaded(provider);
      this._populateModelDropdown(provider);
      document.getElementById('setting-llm-model').value = '';  // Reset model selection
    });

    document.getElementById('setting-completion-guard-eval-provider')?.addEventListener('change', async (e) => {
      const provider = this._getCompletionGuardEvalProviderSelection(e.target.value);
      await this._ensureProviderModelsLoaded(provider);
      this._populateCompletionGuardEvalModelDropdown(provider);
      document.getElementById('setting-completion-guard-eval-model').value = '';
    });
    
    // Reset to defaults button
    document.getElementById('resetDefaultsBtn')?.addEventListener('click', () => {
      this._resetToDefaults();
    });
    
    // Add blocked tool button
    document.getElementById('addBlockedToolBtn')?.addEventListener('click', () => {
      this._addBlockedTool();
    });
    
    // Logout button
    document.getElementById('logoutBtn')?.addEventListener('click', () => {
      if (confirm('Sign out from all Jarvis UIs?')) {
        Utils.auth.logout();
      }
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
    
    // Conversation ID badge - click to copy
    if (this.convIdBadge) {
      this.convIdBadge.addEventListener('click', () => {
        const convId = this.socket.conversationId;
        if (!convId) return;
        
        const onCopied = () => {
          this.convIdBadge.classList.add('copied');
          const orig = this.convIdText.textContent;
          this.convIdText.textContent = 'copied!';
          setTimeout(() => {
            this.convIdText.textContent = orig;
            this.convIdBadge.classList.remove('copied');
          }, 1200);
        };
        
        // navigator.clipboard requires HTTPS — fallback for HTTP
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(convId).then(onCopied);
        } else {
          const ta = document.createElement('textarea');
          ta.value = convId;
          ta.style.position = 'fixed';
          ta.style.opacity = '0';
          document.body.appendChild(ta);
          ta.select();
          document.execCommand('copy');
          document.body.removeChild(ta);
          onCopied();
        }
      });
    }

    document.addEventListener('click', (e) => {
      if (!e.target.closest('.history-menu')) {
        this._closeConversationMenus();
      }
    });
    
    // Conversation filter (quick filter by title)
    const filterInput = document.getElementById('conversationFilter');
    if (filterInput) {
      filterInput.addEventListener('input', (e) => {
        this._filterConversations(e.target.value);
      });
    }
    
    // Deep search button
    const deepSearchBtn = document.getElementById('deepSearchBtn');
    if (deepSearchBtn) {
      deepSearchBtn.addEventListener('click', () => {
        this._openSearchModal();
      });
    }
    
    // Search modal
    const searchModal = document.getElementById('searchModal');
    const closeSearch = document.getElementById('closeSearch');
    const deepSearchInput = document.getElementById('deepSearchInput');
    const doDeepSearch = document.getElementById('doDeepSearch');
    
    if (closeSearch) {
      closeSearch.addEventListener('click', () => {
        searchModal.classList.remove('active');
      });
    }
    
    if (searchModal) {
      searchModal.addEventListener('click', (e) => {
        if (e.target === searchModal) {
          searchModal.classList.remove('active');
        }
      });
    }
    
    if (doDeepSearch) {
      doDeepSearch.addEventListener('click', () => {
        this._doDeepSearch();
      });
    }
    
    if (deepSearchInput) {
      deepSearchInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
          this._doDeepSearch();
        }
      });
    }
    
    // Export/Import modal
    const exportModal = document.getElementById('exportModal');
    const closeExport = document.getElementById('closeExport');
    const exportImportBtn = document.getElementById('exportImportBtn');
    const exportJson = document.getElementById('exportJson');
    const exportMarkdown = document.getElementById('exportMarkdown');
    const importBtn = document.getElementById('importBtn');
    const importFile = document.getElementById('importFile');
    
    if (exportImportBtn) {
      exportImportBtn.addEventListener('click', () => {
        exportModal.classList.add('active');
      });
    }
    
    if (closeExport) {
      closeExport.addEventListener('click', () => {
        exportModal.classList.remove('active');
      });
    }
    
    if (exportModal) {
      exportModal.addEventListener('click', (e) => {
        if (e.target === exportModal) {
          exportModal.classList.remove('active');
        }
      });
    }
    
    if (exportJson) {
      exportJson.addEventListener('click', () => {
        this._exportConversation('json');
      });
    }
    
    if (exportMarkdown) {
      exportMarkdown.addEventListener('click', () => {
        this._exportConversation('markdown');
      });
    }
    
    if (importBtn) {
      importBtn.addEventListener('click', () => {
        importFile.click();
      });
    }
    
    if (importFile) {
      importFile.addEventListener('change', (e) => {
        if (e.target.files[0]) {
          this._importConversation(e.target.files[0]);
        }
      });
    }
    
    // Clear chat button
    const clearChatBtn = document.getElementById('clearChatBtn');
    if (clearChatBtn) {
      clearChatBtn.addEventListener('click', () => this._clearChat());
    }
    
    // Import knowledge button
    const importKnowledgeBtn = document.getElementById('importKnowledgeBtn');
    const importKnowledgeModal = document.getElementById('importKnowledgeModal');
    const closeImportKnowledge = document.getElementById('closeImportKnowledge');
    const importKnowledgeBtnModal = document.getElementById('importKnowledgeBtnModal');
    const importKnowledgeFile = document.getElementById('importKnowledgeFile');
    if (importKnowledgeBtn) {
      importKnowledgeBtn.addEventListener('click', () => {
        importKnowledgeModal?.classList.add('active');
        document.getElementById('importKnowledgeStatus').textContent = '';
      });
    }
    if (closeImportKnowledge) {
      closeImportKnowledge.addEventListener('click', () => importKnowledgeModal?.classList.remove('active'));
    }
    if (importKnowledgeModal) {
      importKnowledgeModal.addEventListener('click', (e) => {
        if (e.target === importKnowledgeModal) importKnowledgeModal.classList.remove('active');
      });
    }
    if (importKnowledgeBtnModal) {
      importKnowledgeBtnModal.addEventListener('click', () => importKnowledgeFile?.click());
    }
    if (importKnowledgeFile) {
      importKnowledgeFile.addEventListener('change', (e) => {
        if (e.target.files[0]) this._importKnowledge(e.target.files[0]);
      });
    }
    
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
      // Escape to close modal or stop audio
      if (e.key === 'Escape') {
        if (this.settingsModal.classList.contains('active')) {
          this.settingsModal.classList.remove('active');
        } else if (this.currentAudio && this.isPlaying) {
          // Stop audio on Escape if playing
          this.stopAudioPlayback();
          Utils.toast('Audio stopped', 'info', 1500);
        }
      }
      
      // Ctrl/Cmd + / to focus input
      if ((e.ctrlKey || e.metaKey) && e.key === '/') {
        e.preventDefault();
        document.getElementById('chatInput').focus();
      }
      
      // Space to toggle audio playback (when not typing)
      if (e.key === ' ' && document.activeElement.tagName !== 'TEXTAREA' && 
          document.activeElement.tagName !== 'INPUT' && this.currentAudio) {
        e.preventDefault();
        this.toggleAudioPlayback();
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
    
    // Sync audio toggle with server TTS setting on startup
    this._syncAudioWithServer();
  }
  
  /**
   * Sync audio toggle state with server TTS setting
   */
  async _syncAudioWithServer() {
    try {
      const mode = this.socket?.mode || 'cloud';
      const response = await fetch(`/api/settings?mode=${encodeURIComponent(mode)}`);
      const data = await response.json();
      if (data.ok && data.settings) {
        const serverTtsEnabled = data.settings.audio?.tts_enabled || false;
        if (this.audioEnabled !== serverTtsEnabled) {
          this.audioEnabled = serverTtsEnabled;
          Utils.storage.set('audioEnabled', this.audioEnabled);
          this._updateAudioButton();
        }
      }
    } catch (err) {
      console.error('Failed to sync audio setting with server:', err);
    }
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
   * Apply glow intensity setting to body
   */
  _applyGlowIntensity() {
    document.body.setAttribute('data-glow-intensity', this.glowIntensity);
  }
  
  /**
   * Play audio response with controls
   */
  _playAudio(url) {
    console.log('[App] Playing audio:', url);
    
    // Stop any currently playing audio
    if (this.currentAudio) {
      this.currentAudio.pause();
      this.currentAudio = null;
    }
    
    const audio = new Audio(url);
    this.currentAudio = audio;
    
    // Progress bar element
    const progressBar = document.getElementById('speakerProgress');
    
    // Update UI when playback starts
    audio.addEventListener('play', () => {
      this.isPlaying = true;
      this._updateSpeakerButton();
    });
    
    // Update progress bar during playback
    audio.addEventListener('timeupdate', () => {
      if (progressBar && audio.duration) {
        const progress = (audio.currentTime / audio.duration) * 100;
        progressBar.style.width = `${progress}%`;
      }
    });
    
    // Update UI when paused
    audio.addEventListener('pause', () => {
      // Only mark as not playing if actually ended (not just paused)
      if (audio.ended) {
        this.isPlaying = false;
        this._updateSpeakerButton();
      }
    });
    
    // Update UI when playback ends
    audio.addEventListener('ended', () => {
      this.isPlaying = false;
      this._updateSpeakerButton();
      
      // Reset progress bar
      if (progressBar) {
        progressBar.style.width = '0%';
      }
      
      // Keep button visible for replay for 10 seconds, then hide
      setTimeout(() => {
        // Only hide if this is still the same audio (not replaced by new audio)
        if (this.currentAudio === audio) {
          this.currentAudio = null;
          this._updateSpeakerButton();
          
          // Revoke blob URL to free memory
          if (url.startsWith('blob:')) {
            URL.revokeObjectURL(url);
          }
        }
      }, 10000);
    });
    
    // Handle errors
    audio.addEventListener('error', (e) => {
      console.warn('[App] Audio error:', e);
      this.isPlaying = false;
      this.currentAudio = null;
      this._updateSpeakerButton();
      if (progressBar) {
        progressBar.style.width = '0%';
      }
    });
    
    audio.play().catch(err => {
      console.warn('[App] Audio playback failed:', err);
      Utils.toast('Audio playback failed', 'error');
      this.isPlaying = false;
      this.currentAudio = null;
      this._updateSpeakerButton();
      if (progressBar) {
        progressBar.style.width = '0%';
      }
    });
  }
  
  /**
   * Toggle audio playback (pause/resume/replay)
   */
  toggleAudioPlayback() {
    if (!this.currentAudio) return;
    
    if (this.isPlaying) {
      // Currently playing - pause it
      this.currentAudio.pause();
      this.isPlaying = false;
    } else if (this.currentAudio.ended) {
      // Finished - replay from start
      this.currentAudio.currentTime = 0;
      this.currentAudio.play();
      this.isPlaying = true;
    } else {
      // Paused - resume
      this.currentAudio.play();
      this.isPlaying = true;
    }
    this._updateSpeakerButton();
  }
  
  /**
   * Stop audio playback completely
   */
  stopAudioPlayback() {
    if (!this.currentAudio) return;
    
    this.currentAudio.pause();
    this.currentAudio.currentTime = 0;
    this.isPlaying = false;
    this.currentAudio = null;
    this._updateSpeakerButton();
    
    // Reset progress bar
    const progressBar = document.getElementById('speakerProgress');
    if (progressBar) {
      progressBar.style.width = '0%';
    }
  }
  
  /**
   * Update speaker button state based on playback
   */
  _updateSpeakerButton() {
    if (!this.speakerBtn) return;
    
    if (this.currentAudio) {
      // Show speaker button when audio is available
      this.speakerBtn.style.display = 'flex';
      
      if (this.isPlaying) {
        // Currently playing
        this.speakerBtn.classList.add('playing');
        this.speakerBtn.classList.remove('paused', 'finished');
        this.speakerBtn.title = 'Click to pause | Double-click to stop';
      } else if (this.currentAudio.ended) {
        // Finished - available for replay
        this.speakerBtn.classList.add('finished');
        this.speakerBtn.classList.remove('playing', 'paused');
        this.speakerBtn.title = 'Click to replay audio';
      } else {
        // Paused mid-playback
        this.speakerBtn.classList.add('paused');
        this.speakerBtn.classList.remove('playing', 'finished');
        this.speakerBtn.title = 'Click to resume | Double-click to stop';
      }
    } else {
      // Hide speaker button when no audio
      this.speakerBtn.style.display = 'none';
      this.speakerBtn.classList.remove('playing', 'paused', 'finished');
    }
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
        
        // Group tools (include 'database' source with local tools for auto-generated tools)
        const localTools = tools.filter(t => (t.source === 'local' || t.source === 'database') && !t.blocked);
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
        this._setupToolHoverTooltips(container);
      } else {
        container.innerHTML = '<p style="color: var(--error); padding: var(--space-md);">Failed to load tools</p>';
      }
    } catch (err) {
      container.innerHTML = `<p style="color: var(--error); padding: var(--space-md);">Error: ${err.message}</p>`;
    }
  }
  
  /**
   * Setup hover tooltips for tool items (desktop only)
   * Tooltip stays visible when hovering over item OR tooltip, with delay before hide
   * so user can move mouse into tooltip to scroll long descriptions.
   */
  /**
   * Chat history row titles: fixed-position tooltip (not clipped by .history-list).
   * Show delay avoids flicker; hide is immediate on row leave so moving down the list
   * can open the next tooltip without the previous one trapping the pointer.
   */
  _setupHistoryTitleTooltips(container) {
    if (!window.matchMedia('(hover: hover)').matches) return;
    const gap = 6;
    const maxTooltipWidth = 320;
    const showDelayMs = 380;
    const hideAllTooltips = () => {
      container.querySelectorAll('.history-title-tooltip').forEach(el => {
        el.style.display = 'none';
      });
    };
    container.querySelectorAll('.history-item').forEach(item => {
      const tooltip = item.querySelector('.history-title-tooltip');
      if (!tooltip) return;
      let showTimeout = null;
      const clearShow = () => {
        if (showTimeout) {
          clearTimeout(showTimeout);
          showTimeout = null;
        }
      };
      const positionAndShow = () => {
        const rect = item.getBoundingClientRect();
        const w = Math.min(maxTooltipWidth, window.innerWidth - 16);
        tooltip.style.display = 'block';
        tooltip.style.position = 'fixed';
        tooltip.style.left = `${rect.left}px`;
        tooltip.style.top = `${rect.bottom + gap}px`;
        tooltip.style.width = `${w}px`;
        tooltip.style.maxWidth = `${w}px`;
        tooltip.style.zIndex = '10050';
        tooltip.style.boxSizing = 'border-box';
        requestAnimationFrame(() => {
          const tr = tooltip.getBoundingClientRect();
          let top = rect.bottom + gap;
          if (tr.bottom > window.innerHeight - 8) {
            top = Math.max(8, rect.top - tr.height - gap);
          }
          let left = rect.left;
          if (left + tr.width > window.innerWidth - 8) {
            left = Math.max(8, window.innerWidth - tr.width - 8);
          }
          tooltip.style.top = `${top}px`;
          tooltip.style.left = `${left}px`;
        });
      };
      const onEnter = () => {
        clearShow();
        hideAllTooltips();
        showTimeout = setTimeout(() => {
          showTimeout = null;
          positionAndShow();
        }, showDelayMs);
      };
      const onLeave = () => {
        clearShow();
        tooltip.style.display = 'none';
      };
      item.addEventListener('mouseenter', onEnter);
      item.addEventListener('mouseleave', onLeave);
    });
    container.onscroll = () => {
      hideAllTooltips();
    };
  }
  
  _setupToolHoverTooltips(container) {
    if (!window.matchMedia('(hover: hover)').matches) return;
    const gap = 4;
    container.querySelectorAll('.tool-item').forEach(item => {
      const tooltip = item.querySelector('.tool-item-tooltip');
      if (!tooltip) return;
      item.removeAttribute('title');
      let hideTimeout = null;
      const scheduleHide = () => {
        if (hideTimeout) clearTimeout(hideTimeout);
        hideTimeout = setTimeout(() => {
          tooltip.style.display = 'none';
          hideTimeout = null;
        }, 150);
      };
      const cancelHide = () => {
        if (hideTimeout) clearTimeout(hideTimeout);
        hideTimeout = null;
      };
      const show = () => {
        cancelHide();
        const rect = item.getBoundingClientRect();
        tooltip.style.display = 'block';
        tooltip.style.left = `${rect.right + gap}px`;
        tooltip.style.top = `${rect.top}px`;
        const tooltipRect = tooltip.getBoundingClientRect();
        if (tooltipRect.right > window.innerWidth) {
          tooltip.style.left = `${Math.max(8, rect.left - tooltipRect.width - gap)}px`;
        }
        if (tooltipRect.bottom > window.innerHeight) {
          tooltip.style.top = `${window.innerHeight - tooltipRect.height - 8}px`;
        }
      };
      item.addEventListener('mouseenter', show);
      item.addEventListener('mouseleave', scheduleHide);
      tooltip.addEventListener('mouseenter', show);
      tooltip.addEventListener('mouseleave', scheduleHide);
    });
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
    
    const tooltipDesc = Utils.escapeHtml(Utils.truncate(desc, 2000));
    
    return `
      <div class="${classes.join(' ')}" title="${Utils.escapeHtml(tool.description || tool.name)}">
        <div class="tool-item-name">${emoji} ${Utils.escapeHtml(tool.name)} ${badge}</div>
        <div class="tool-item-desc">${Utils.escapeHtml(Utils.truncate(desc, 500))}</div>
        <div class="tool-item-tooltip" aria-hidden="true">${tooltipDesc}</div>
      </div>
    `;
  }
  
  /**
   * Get emoji for tool based on name
   */
  _getToolEmoji(name) {
    const n = String(name || '').trim();
    /** @type {Record<string, string>} */
    const emojiMap = {
      phone_call: '📞',
      spotify: '🎵',
      generate_image: '🖼️',
      generate_music: '🎵',
      generate_video: '🎬',
      send_email: '✉️',
      send_webhook: '🔗',
      printer: '🖨️',
      weather: '🌤️',
      remember: '💾',
      recall: '🧠',
      forget: '🗑️',
      search_memory: '🔍',
      semantic_recall: '🔍',
      deep_memory_search: '🧠',
      update_memory: '✏️',
      memory_deduper: '🧹',
      canvas: '📝',
      stash: '📦',
      pdf_create: '📄',
      pdf_read: '📖',
      crypto_price: '💰',
      crypto_chart: '📈',
      stock_price: '📊',
      price_alert: '🔔',
      opencode: '💻',
      check_opencode_sessions: '🖥️',
      serpapi_search: '🔎',
      serpapi_maps_search: '🗺️',
      serpapi_hotel_search: '🏨',
      serpapi_youtube: '▶️',
      serpapi_youtube_search: '▶️',
      serpapi_yelp_search: '⭐',
      serpapi_home_depot: '🛒',
      serpapi_ebay_search: '🛒',
      serpapi_ebay_product: '🛒',
      brave_llm_context: '🦁',
      crawl_url: '🕷️',
      bookmark_search: '🔖',
      search_docs: '📚',
      search_conversations: '💬',
      get_recent_conversations: '📜',
      youtube_transcript: '📝',
      youtube_video: '📺',
      ingest_intel: '📥',
      manage_intel: '🗂️',
      supa_crawl_knowledge: '🔍',
      git_release_notes: '📌',
      list_reminders: '📋',
      create_reminder: '⏰',
      acknowledge_reminders: '✅',
      create_alert: '🔔',
      list_alerts: '📋',
      acknowledge_alerts: '✅',
      system_monitor: '📊',
      network_tools: '🌐',
      docker_control: '🐳',
      ssh_remote: '🔐',
      execute_bash: '⌨️',
      speaker_volume: '🔊',
      calculator: '🔢',
      get_time: '🕐',
      schedule_task: '📅',
      api_call: '🌐',
      analyze_image: '🖼️',
      screenshot_url: '📸',
      convert_file: '🔄',
      text_summarizer: '📃',
      qr_code_generator: '🔳',
      generate_password: '🔑',
      upload_cloudflare: '☁️',
      tool_search: '🧰',
      check_tool_logs: '📋',
      query_service_logs: '📋',
      evolution_test: '🧬',
      samantha: '🤖',
      status_recap: '📋',
    };

    if (emojiMap[n]) {
      return emojiMap[n];
    }

    if (n.startsWith('mcp_')) {
      return '🔌';
    }
    if (n.startsWith('serpapi_')) {
      if (n.includes('maps')) return '🗺️';
      if (n.includes('hotel')) return '🏨';
      if (n.includes('youtube')) return '▶️';
      if (n.includes('yelp')) return '⭐';
      if (n.includes('ebay') || n.includes('home_depot')) return '🛒';
      return '🔎';
    }
    if (n.startsWith('generate_')) {
      if (n.includes('music')) return '🎵';
      if (n.includes('video')) return '🎬';
      if (n.includes('image')) return '🖼️';
      if (n.includes('password')) return '🔑';
      return '✨';
    }
    if (n.includes('memory') || n === 'forget' || n === 'recall') {
      return '🧠';
    }
    if (n.includes('reminder') || n.includes('alert')) {
      if (n.startsWith('list_') || n.startsWith('acknowledge')) return '✅';
      return '⏰';
    }
    if (n.startsWith('search_') || n.endsWith('_search')) {
      return '🔍';
    }
    if (n.startsWith('crypto_') || n.startsWith('stock_')) {
      return '📈';
    }
    if (n.startsWith('pdf_')) {
      return '📄';
    }
    if (n.startsWith('youtube_')) {
      return '📺';
    }
    if (n.includes('docker')) {
      return '🐳';
    }
    if (n.includes('ssh') || n.includes('bash')) {
      return '⌨️';
    }

    return '🔧';
  }

  _getCachedEffectiveResponseStyle() {
    const responseSettings = this._settingsData?.response;
    return responseSettings?.style?.value
      || responseSettings?.style?.default
      || 'auto';
  }

  async _getEffectiveResponseStyle() {
    if (this._settingsData?.mode === this.socket.mode && this._settingsData?.response?.style) {
      return this._getCachedEffectiveResponseStyle();
    }

    try {
      const mode = this.socket?.mode || 'cloud';
      const response = await fetch(`/api/settings?mode=${encodeURIComponent(mode)}`);
      const data = await response.json();
      if (data.ok && data.settings) {
        this._settingsData = data.settings;
        return this._getCachedEffectiveResponseStyle();
      }
    } catch (err) {
      console.warn('[App] Failed to fetch settings for response style:', err);
    }

    return 'auto';
  }

  _applyLocalSettingsUpdate(settingsPayload = {}) {
    if (!this._settingsData) {
      this._settingsData = { mode: this.socket.mode, audio: {}, response: {} };
    }

    this._settingsData.mode = this.socket.mode;
    this._settingsData.audio = this._settingsData.audio || {};
    this._settingsData.response = this._settingsData.response || {};

    if (Object.prototype.hasOwnProperty.call(settingsPayload, 'tts_enabled')) {
      this._settingsData.audio.tts_enabled = !!settingsPayload.tts_enabled;
    }

    if (Object.prototype.hasOwnProperty.call(settingsPayload, 'response_style')) {
      const styleValue = settingsPayload.response_style || null;
      const defaultStyle = this._settingsData.response.style?.default || 'auto';
      this._settingsData.response.style = {
        value: styleValue || defaultStyle,
        default: defaultStyle,
        is_override: !!styleValue,
      };

      const responseStyleSelect = document.getElementById('setting-response-style');
      if (responseStyleSelect) {
        responseStyleSelect.value = styleValue || '';
      }

      const responseStyleDefault = document.getElementById('response-style-default');
      if (responseStyleDefault) {
        if (styleValue) {
          responseStyleDefault.textContent = `⚡ override: ${styleValue}`;
          responseStyleDefault.className = 'setting-default setting-override';
        } else {
          const envFile = this.socket.mode === 'local' ? 'local.env' : 'cloud.env';
          responseStyleDefault.textContent = `(${envFile}: ${defaultStyle})`;
          responseStyleDefault.className = 'setting-default';
        }
      }
    }
  }

  /**
   * Load and display settings
   */
  async _loadSettings() {
    try {
      const mode = this.socket?.mode || 'cloud';
      const response = await fetch(`/api/settings?mode=${encodeURIComponent(mode)}`);
      const data = await response.json();
      
      if (data.ok && data.settings) {
        const s = data.settings;
        this._settingsData = s;  // Cache for later use
        this._configureProviderSelectLabels();
        this._filterSelectOptions(
          document.getElementById('setting-llm-provider'),
          s.llm?.provider?.options || []
        );
        this._filterSelectOptions(
          document.getElementById('setting-tts-provider'),
          s.tts?.provider?.options || []
        );
        
        // Populate General settings
        document.getElementById('setting-mode').value = s.mode || 'cloud';
        document.getElementById('setting-tts').checked = s.audio?.tts_enabled || false;
        document.getElementById('setting-progress-events').checked = s.ui?.progress_events !== false;  // Default true
        document.getElementById('setting-glow-intensity').value = this.glowIntensity;
        
        // Sync audio toggle button with server TTS setting
        this.audioEnabled = s.audio?.tts_enabled || false;
        Utils.storage.set('audioEnabled', this.audioEnabled);
        this._updateAudioButton();
        
        // Populate LLM Provider
        const providerSelect = document.getElementById('setting-llm-provider');
        providerSelect.value = s.llm?.provider?.is_override ? s.llm.provider.value : '';
        const providerDefault = document.getElementById('llm-provider-default');
        const envFile = s.mode === 'local' ? 'local.env' : 'cloud.env';
        const provEnvDefault = s.llm?.provider?.default || 'xai';
        if (s.llm?.provider?.is_override) {
          providerDefault.textContent = `⚡ override: ${s.llm.provider.value} · (${envFile} default: ${provEnvDefault})`;
          providerDefault.className = 'setting-default setting-override';
        } else {
          providerDefault.textContent = `(${envFile}: ${provEnvDefault})`;
          providerDefault.className = 'setting-default';
        }
        
        // Populate LLM Model dropdown based on provider
        await this._ensureProviderModelsLoaded(s.llm?.provider?.value || s.llm?.provider?.default || 'xai');
        this._populateModelDropdown(s.llm?.provider?.value || s.llm?.provider?.default || 'xai');
        const modelSelect = document.getElementById('setting-llm-model');
        modelSelect.value = s.llm?.model?.is_override ? s.llm.model.value : '';
        const modelDefault = document.getElementById('llm-model-default');
        const modelEnvDefault = s.llm?.model?.default || 'default';
        if (s.llm?.model?.is_override) {
          modelDefault.textContent = `⚡ override: ${s.llm.model.value} · (${envFile} default: ${modelEnvDefault})`;
          modelDefault.className = 'setting-default setting-override';
        } else {
          modelDefault.textContent = `(${envFile}: ${modelEnvDefault})`;
          modelDefault.className = 'setting-default';
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
        
        // Populate Video Provider
        const videoSelect = document.getElementById('setting-video-provider');
        videoSelect.value = s.video?.provider?.is_override ? s.video.provider.value : '';
        const videoDefault = document.getElementById('video-provider-default');
        videoDefault.textContent = `(${envFile}: ${s.video?.provider?.default || 'xai'})`;
        videoDefault.className = s.video?.provider?.is_override ? 'setting-default setting-override' : 'setting-default';
        if (s.video?.provider?.is_override) {
          videoDefault.textContent = `⚡ override: ${s.video.provider.value}`;
        }

        // Populate TTS Provider
        const ttsSelect = document.getElementById('setting-tts-provider');
        ttsSelect.value = s.tts?.provider?.is_override ? s.tts.provider.value : '';
        const ttsDefault = document.getElementById('tts-provider-default');
        ttsDefault.textContent = `(${envFile}: ${s.tts?.provider?.default || 'elevenlabs'})`;
        ttsDefault.className = s.tts?.provider?.is_override ? 'setting-default setting-override' : 'setting-default';
        if (s.tts?.provider?.is_override) {
          ttsDefault.textContent = `⚡ override: ${s.tts.provider.value}`;
        }

        // Populate Response Style
        const responseStyleSelect = document.getElementById('setting-response-style');
        responseStyleSelect.value = s.response?.style?.is_override ? s.response.style.value : '';
        const responseStyleDefault = document.getElementById('response-style-default');
        responseStyleDefault.textContent = `(${envFile}: ${s.response?.style?.default || 'auto'})`;
        responseStyleDefault.className = s.response?.style?.is_override ? 'setting-default setting-override' : 'setting-default';
        if (s.response?.style?.is_override) {
          responseStyleDefault.textContent = `⚡ override: ${s.response.style.value}`;
        }

        // Populate QA Word Limit
        const qaWordLimitInput = document.getElementById('setting-qa-word-limit');
        qaWordLimitInput.value = s.response?.qa_word_limit?.is_override ? s.response.qa_word_limit.value : '';
        qaWordLimitInput.placeholder = `${s.response?.qa_word_limit?.default || 75}`;
        const qaWordLimitDefault = document.getElementById('qa-word-limit-default');
        qaWordLimitDefault.textContent = `(${envFile}: ${s.response?.qa_word_limit?.default || 75})`;
        qaWordLimitDefault.className = s.response?.qa_word_limit?.is_override ? 'setting-default setting-override' : 'setting-default';
        if (s.response?.qa_word_limit?.is_override) {
          qaWordLimitDefault.textContent = `⚡ override: ${s.response.qa_word_limit.value}`;
        }

        // Populate Multi-Turn Word Limit
        const multiTurnWordLimitInput = document.getElementById('setting-multi-turn-word-limit');
        multiTurnWordLimitInput.value = s.response?.multi_turn_word_limit?.is_override ? s.response.multi_turn_word_limit.value : '';
        multiTurnWordLimitInput.placeholder = `${s.response?.multi_turn_word_limit?.default || 50}`;
        const multiTurnWordLimitDefault = document.getElementById('multi-turn-word-limit-default');
        multiTurnWordLimitDefault.textContent = `(${envFile}: ${s.response?.multi_turn_word_limit?.default || 50})`;
        multiTurnWordLimitDefault.className = s.response?.multi_turn_word_limit?.is_override ? 'setting-default setting-override' : 'setting-default';
        if (s.response?.multi_turn_word_limit?.is_override) {
          multiTurnWordLimitDefault.textContent = `⚡ override: ${s.response.multi_turn_word_limit.value}`;
        }

        // Populate Completion Guard settings
        const completionGuardEnabledInput = document.getElementById('setting-completion-guard-enabled');
        completionGuardEnabledInput.value = s.completion_guard?.enabled?.is_override
          ? String(!!s.completion_guard.enabled.value)
          : '';
        const completionGuardEnabledDefault = document.getElementById('completion-guard-enabled-default');
        completionGuardEnabledDefault.textContent = `(${envFile}: ${s.completion_guard?.enabled?.default ? 'on' : 'off'})`;
        completionGuardEnabledDefault.className = s.completion_guard?.enabled?.is_override ? 'setting-default setting-override' : 'setting-default';
        if (s.completion_guard?.enabled?.is_override) {
          completionGuardEnabledDefault.textContent = `⚡ override: ${s.completion_guard.enabled.value ? 'on' : 'off'}`;
        }

        const completionGuardModeInput = document.getElementById('setting-completion-guard-mode');
        completionGuardModeInput.value = s.completion_guard?.mode?.is_override ? s.completion_guard.mode.value : '';
        const completionGuardModeDefault = document.getElementById('completion-guard-mode-default');
        completionGuardModeDefault.textContent = `(${envFile}: ${s.completion_guard?.mode?.default || 'manual'})`;
        completionGuardModeDefault.className = s.completion_guard?.mode?.is_override ? 'setting-default setting-override' : 'setting-default';
        if (s.completion_guard?.mode?.is_override) {
          completionGuardModeDefault.textContent = `⚡ override: ${s.completion_guard.mode.value}`;
        }

        const completionGuardAutoThresholdInput = document.getElementById('setting-completion-guard-auto-threshold');
        completionGuardAutoThresholdInput.value = s.completion_guard?.auto_threshold?.is_override
          ? s.completion_guard.auto_threshold.value
          : '';
        completionGuardAutoThresholdInput.placeholder = `${s.completion_guard?.auto_threshold?.default ?? 0.7}`;
        const completionGuardAutoThresholdDefault = document.getElementById('completion-guard-auto-threshold-default');
        completionGuardAutoThresholdDefault.textContent = `(${envFile}: ${s.completion_guard?.auto_threshold?.default ?? 0.7})`;
        completionGuardAutoThresholdDefault.className = s.completion_guard?.auto_threshold?.is_override ? 'setting-default setting-override' : 'setting-default';
        if (s.completion_guard?.auto_threshold?.is_override) {
          completionGuardAutoThresholdDefault.textContent = `⚡ override: ${s.completion_guard.auto_threshold.value}`;
        }

        this._configureCompletionGuardEvalProviderSelect();
        const completionGuardEvalProviderInput = document.getElementById('setting-completion-guard-eval-provider');
        completionGuardEvalProviderInput.value = s.completion_guard?.eval_provider?.is_override
          ? s.completion_guard.eval_provider.value
          : '';
        const completionGuardEvalProviderDefault = document.getElementById('completion-guard-eval-provider-default');
        completionGuardEvalProviderDefault.textContent = `(${envFile}: ${s.completion_guard?.eval_provider?.default || (s.mode === 'local' ? 'ollama' : 'openai')})`;
        completionGuardEvalProviderDefault.className = s.completion_guard?.eval_provider?.is_override ? 'setting-default setting-override' : 'setting-default';
        if (s.completion_guard?.eval_provider?.is_override) {
          completionGuardEvalProviderDefault.textContent = `⚡ override: ${s.completion_guard.eval_provider.value}`;
        }

        const completionGuardEvalProvider = this._getCompletionGuardEvalProviderSelection(
          s.completion_guard?.eval_provider?.value
            || s.completion_guard?.eval_provider?.default
            || (s.mode === 'local' ? 'ollama' : 'openai')
        );
        await this._ensureProviderModelsLoaded(completionGuardEvalProvider);
        this._populateCompletionGuardEvalModelDropdown(completionGuardEvalProvider);
        const completionGuardEvalModelInput = document.getElementById('setting-completion-guard-eval-model');
        completionGuardEvalModelInput.value = s.completion_guard?.eval_model?.is_override
          ? s.completion_guard.eval_model.value
          : '';
        const completionGuardEvalModelDefault = document.getElementById('completion-guard-eval-model-default');
        completionGuardEvalModelDefault.textContent = `(${envFile}: ${s.completion_guard?.eval_model?.default || 'provider default'})`;
        completionGuardEvalModelDefault.className = s.completion_guard?.eval_model?.is_override ? 'setting-default setting-override' : 'setting-default';
        if (s.completion_guard?.eval_model?.is_override) {
          completionGuardEvalModelDefault.textContent = `⚡ override: ${s.completion_guard.eval_model.value}`;
        }

        const completionGuardTicketInput = document.getElementById('setting-completion-guard-ticket-on-fail');
        completionGuardTicketInput.value = s.completion_guard?.ticket_on_fail?.is_override
          ? String(!!s.completion_guard.ticket_on_fail.value)
          : '';
        const completionGuardTicketDefault = document.getElementById('completion-guard-ticket-default');
        completionGuardTicketDefault.textContent = `(${envFile}: ${s.completion_guard?.ticket_on_fail?.default ? 'on' : 'off'})`;
        completionGuardTicketDefault.className = s.completion_guard?.ticket_on_fail?.is_override ? 'setting-default setting-override' : 'setting-default';
        if (s.completion_guard?.ticket_on_fail?.is_override) {
          completionGuardTicketDefault.textContent = `⚡ override: ${s.completion_guard.ticket_on_fail.value ? 'on' : 'off'}`;
        }

        const completionGuardPromptInput = document.getElementById('setting-completion-guard-show-ui-prompt');
        completionGuardPromptInput.value = s.completion_guard?.show_ui_prompt?.is_override
          ? String(!!s.completion_guard.show_ui_prompt.value)
          : '';
        const completionGuardPromptDefault = document.getElementById('completion-guard-prompt-default');
        completionGuardPromptDefault.textContent = `(${envFile}: ${s.completion_guard?.show_ui_prompt?.default ? 'on' : 'off'})`;
        completionGuardPromptDefault.className = s.completion_guard?.show_ui_prompt?.is_override ? 'setting-default setting-override' : 'setting-default';
        if (s.completion_guard?.show_ui_prompt?.is_override) {
          completionGuardPromptDefault.textContent = `⚡ override: ${s.completion_guard.show_ui_prompt.value ? 'on' : 'off'}`;
        }

        const completionGuardQaInput = document.getElementById('setting-completion-guard-include-qa');
        completionGuardQaInput.value = s.completion_guard?.include_qa?.is_override
          ? String(!!s.completion_guard.include_qa.value)
          : '';
        const completionGuardQaDefault = document.getElementById('completion-guard-qa-default');
        completionGuardQaDefault.textContent = `(${envFile}: ${s.completion_guard?.include_qa?.default ? 'on' : 'off'})`;
        completionGuardQaDefault.className = s.completion_guard?.include_qa?.is_override ? 'setting-default setting-override' : 'setting-default';
        if (s.completion_guard?.include_qa?.is_override) {
          completionGuardQaDefault.textContent = `⚡ override: ${s.completion_guard.include_qa.value ? 'on' : 'off'}`;
        }

        const completionGuardToolsInput = document.getElementById('setting-completion-guard-include-tool-tasks');
        completionGuardToolsInput.value = s.completion_guard?.include_tool_tasks?.is_override
          ? String(!!s.completion_guard.include_tool_tasks.value)
          : '';
        const completionGuardToolsDefault = document.getElementById('completion-guard-tools-default');
        completionGuardToolsDefault.textContent = `(${envFile}: ${s.completion_guard?.include_tool_tasks?.default ? 'on' : 'off'})`;
        completionGuardToolsDefault.className = s.completion_guard?.include_tool_tasks?.is_override ? 'setting-default setting-override' : 'setting-default';
        if (s.completion_guard?.include_tool_tasks?.is_override) {
          completionGuardToolsDefault.textContent = `⚡ override: ${s.completion_guard.include_tool_tasks.value ? 'on' : 'off'}`;
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
        
        // Populate Profile section
        this._updateProfileSection(s);
      }
      
      // Load system config / effective runtime values
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
        const s = this._settingsData || {};
        const effectiveProvider = s.llm?.provider?.value || c.LLM_PROVIDER;
        const effectiveModel = s.llm?.model?.value || c[`${String(effectiveProvider).toUpperCase()}_MODEL`] || c.OLLAMA_MODEL || '(provider default)';
        const effectiveCgEvalProvider = s.completion_guard?.eval_provider?.value || c.JARVIS_COMPLETION_GUARD_EVAL_PROVIDER;
        const effectiveCgEvalModel = s.completion_guard?.eval_model?.value || c.JARVIS_COMPLETION_GUARD_EVAL_MODEL || '(provider default)';
        const effectiveResponseStyle = s.response?.style?.value || c.JARVIS_RESPONSE_STYLE;
        const effectiveQaLimit = s.response?.qa_word_limit?.value ?? c.JARVIS_QA_WORD_LIMIT;
        const effectiveMultiTurnLimit = s.response?.multi_turn_word_limit?.value ?? c.JARVIS_MULTI_TURN_WORD_LIMIT;
        const effectiveCgEnabled = s.completion_guard?.enabled?.value ?? (c.JARVIS_COMPLETION_GUARD_ENABLED === 'true');
        const effectiveCgMode = s.completion_guard?.mode?.value || c.JARVIS_COMPLETION_GUARD_MODE;
        const effectiveCgThreshold = s.completion_guard?.auto_threshold?.value ?? c.JARVIS_COMPLETION_GUARD_AUTO_THRESHOLD;
        const effectiveTtsProvider = s.tts?.provider?.value || c.TTS_PROVIDER;
        const ttsProvider = String(effectiveTtsProvider || '').toLowerCase();
        
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

        const audioProviderHtml = ttsProvider === 'qwen3-tts'
          ? `
            <div class="config-item">
              <span class="config-label">QWEN3_TTS_URL</span>
              <span class="config-value">${c.QWEN3_TTS_URL || '(not set)'}</span>
            </div>
            <div class="config-item">
              <span class="config-label">QWEN3_TTS_VOICE</span>
              <span class="config-value">${c.QWEN3_TTS_VOICE || '(default)'}</span>
            </div>
            <div class="config-item">
              <span class="config-label">QWEN3_TTS_FORMAT</span>
              <span class="config-value">${c.QWEN3_TTS_FORMAT || 'mp3'}</span>
            </div>
          `
          : isLocal ? `
            <div class="config-item">
              <span class="config-label">KOKORO_TTS_URL</span>
              <span class="config-value">${c.KOKORO_TTS_URL || '(not set)'}</span>
            </div>
            <div class="config-item">
              <span class="config-label">KOKORO_TTS_VOICE</span>
              <span class="config-value">${c.KOKORO_TTS_VOICE || '(default)'}</span>
            </div>
          `
          : ttsProvider === 'xai' ? `
            <div class="config-item">
              <span class="config-label">XAI_TTS_VOICE</span>
              <span class="config-value">${c.XAI_TTS_VOICE || '(default)'}</span>
            </div>
            <div class="config-item">
              <span class="config-label">XAI_TTS_LANGUAGE</span>
              <span class="config-value">${c.XAI_TTS_LANGUAGE || 'en'}</span>
            </div>
            <div class="config-item">
              <span class="config-label">XAI_TTS_CODEC</span>
              <span class="config-value">${c.XAI_TTS_CODEC || 'mp3'}</span>
            </div>
            <div class="config-item">
              <span class="config-label">XAI_TTS_TIMEOUT</span>
              <span class="config-value">${c.XAI_TTS_TIMEOUT || '180'}s</span>
            </div>
          ` : ttsProvider === 'openai' ? `
            <div class="config-item">
              <span class="config-label">TTS_MODEL</span>
              <span class="config-value">${c.TTS_MODEL || 'gpt-4o-mini-tts'}</span>
            </div>
            <div class="config-item">
              <span class="config-label">VOICE</span>
              <span class="config-value">${c.VOICE || '(default)'}</span>
            </div>
          ` : `
            <div class="config-item">
              <span class="config-label">ELEVENLABS_TTS_MODEL</span>
              <span class="config-value">${c.ELEVENLABS_TTS_MODEL || 'eleven_multilingual_v2'}</span>
            </div>
            <div class="config-item">
              <span class="config-label">ELEVENLABS_TTS_VOICE</span>
              <span class="config-value">${c.ELEVENLABS_TTS_VOICE || '(default)'}</span>
            </div>
            ${ttsProvider === 'elevenlabs' ? `
            <div class="config-item" id="elevenlabs-usage">
              <span class="config-label">Usage</span>
              <span class="config-value loading">Loading...</span>
            </div>
            ` : ''}
          `;
        
        container.innerHTML = `
          <div class="config-section">
            <div class="config-section-title">🎛️ Current Runtime (${isLocal ? 'local mode' : 'cloud mode'})</div>
            <div class="config-item">
              <span class="config-label">LLM</span>
              <span class="config-value">${effectiveProvider} / ${effectiveModel}</span>
            </div>
            <div class="config-item">
              <span class="config-label">Completion Guard</span>
              <span class="config-value ${effectiveCgEnabled ? 'enabled' : 'disabled'}">${effectiveCgEnabled ? effectiveCgMode : 'off'}</span>
            </div>
            <div class="config-item">
              <span class="config-label">CG Eval</span>
              <span class="config-value">${effectiveCgEvalProvider} / ${effectiveCgEvalModel}</span>
            </div>
            <div class="config-item">
              <span class="config-label">Response Formatting</span>
              <span class="config-value">${effectiveResponseStyle} · QA ${effectiveQaLimit} · Multi-turn ${effectiveMultiTurnLimit}</span>
            </div>
            <div class="config-item">
              <span class="config-label">CG Auto Threshold</span>
              <span class="config-value">${effectiveCgThreshold}</span>
            </div>
            <div class="config-item">
              <span class="config-label">TTS</span>
              <span class="config-value">${effectiveTtsProvider}</span>
            </div>
          </div>

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
              <span class="config-label">TOOL_SIMILARITY_THRESHOLD_FULL</span>
              <span class="config-value">${c.TOOL_SIMILARITY_THRESHOLD_FULL || '(unset — same as base for full prompt embedding)'}</span>
            </div>
            <div class="config-item">
              <span class="config-label">SEMANTIC_SIMILARITY_THRESHOLD</span>
              <span class="config-value">${c.SEMANTIC_SIMILARITY_THRESHOLD}</span>
            </div>
          </div>
          
          <div class="config-section">
            <div class="config-section-title">🔊 Audio (${isLocal ? 'Local' : 'Cloud'})</div>
            <div class="config-item">
              <span class="config-label">TTS_PROVIDER</span>
              <span class="config-value">${effectiveTtsProvider}</span>
            </div>
            ${audioProviderHtml}
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
            <div class="config-item">
              <span class="config-label">VIDEO_TOOL_PROVIDER</span>
              <span class="config-value">${c.VIDEO_TOOL_PROVIDER}</span>
            </div>
          </div>
          
          <div class="config-section">
            <div class="config-section-title">🛡️ Completion Guard</div>
            <div class="config-item">
              <span class="config-label">JARVIS_COMPLETION_GUARD_ENABLED</span>
              <span class="config-value ${c.JARVIS_COMPLETION_GUARD_ENABLED === 'true' ? 'enabled' : 'disabled'}">${c.JARVIS_COMPLETION_GUARD_ENABLED}</span>
            </div>
            <div class="config-item">
              <span class="config-label">JARVIS_COMPLETION_GUARD_MODE</span>
              <span class="config-value">${c.JARVIS_COMPLETION_GUARD_MODE}</span>
            </div>
            <div class="config-item">
              <span class="config-label">JARVIS_COMPLETION_GUARD_AUTO_THRESHOLD</span>
              <span class="config-value">${c.JARVIS_COMPLETION_GUARD_AUTO_THRESHOLD}</span>
            </div>
            <div class="config-item">
              <span class="config-label">JARVIS_COMPLETION_GUARD_EVAL_PROVIDER</span>
              <span class="config-value">${c.JARVIS_COMPLETION_GUARD_EVAL_PROVIDER}</span>
            </div>
            <div class="config-item">
              <span class="config-label">JARVIS_COMPLETION_GUARD_EVAL_MODEL</span>
              <span class="config-value">${c.JARVIS_COMPLETION_GUARD_EVAL_MODEL}</span>
            </div>
          </div>

          <div class="config-section">
            <div class="config-section-title">🔄 Feedback/Evolution</div>
            <div class="config-item">
              <span class="config-label">FEEDBACK_RANDOM_ENABLED</span>
              <span class="config-value ${c.FEEDBACK_RANDOM_ENABLED === 'true' ? 'enabled' : 'disabled'}">${c.FEEDBACK_RANDOM_ENABLED}</span>
            </div>
            <div class="config-item">
              <span class="config-label">FEEDBACK_RANDOM_CHANCE</span>
              <span class="config-value">${c.FEEDBACK_RANDOM_CHANCE} (${Math.round(parseFloat(c.FEEDBACK_RANDOM_CHANCE || 0) * 100)}%)</span>
            </div>
            <div class="config-item">
              <span class="config-label">FEEDBACK_PROVIDER</span>
              <span class="config-value">${c.FEEDBACK_PROVIDER}</span>
            </div>
          </div>
          
          <div class="config-section">
            <div class="config-section-title">🌍 System</div>
            <div class="config-item">
              <span class="config-label">JARVIS_TIMEZONE</span>
              <span class="config-value">${c.JARVIS_TIMEZONE}</span>
            </div>
            <div class="config-item">
              <span class="config-label">JARVIS_DEFAULT_LOCATION</span>
              <span class="config-value">${c.JARVIS_DEFAULT_LOCATION || 'Hillsboro, Oregon'}</span>
            </div>
            <div class="config-item">
              <span class="config-label">JARVIS_DEFAULT_POSTAL_CODE</span>
              <span class="config-value">${c.JARVIS_DEFAULT_POSTAL_CODE || 'Not set'}</span>
            </div>
            <div class="config-item">
              <span class="config-label">Mode</span>
              <span class="config-value">${data.mode}</span>
            </div>
          </div>
        `;
        
        // Fetch ElevenLabs usage if in cloud mode
        if (!isLocal && ttsProvider === 'elevenlabs') {
          this._loadElevenLabsUsage();
        }
      }
    } catch (err) {
      console.error('[App] Failed to load system config:', err);
    }
  }
  
  /**
   * Update the profile section with current settings
   */
  async _updateProfileSection(settings) {
    // Update mode display
    const profileMode = document.getElementById('profile-mode');
    if (profileMode) {
      const mode = settings.mode || 'cloud';
      profileMode.textContent = mode === 'cloud' ? '☁️ Cloud' : '💻 Local';
    }
    
    // Fetch status from API for version and auth info
    try {
      const response = await fetch('/api/status');
      const status = await response.json();
      
      // Update version from API
      const versionEl = document.getElementById('profile-version');
      if (versionEl && status.version) {
        versionEl.textContent = `v${status.version}`;
      }
      
      // Update auth status from API (this is the actual server-side auth state)
      const authStatus = document.getElementById('profile-auth-status');
      if (authStatus) {
        const authEnabled = status.features?.auth;
        authStatus.textContent = authEnabled ? '🔒 Secured' : '🔓 Open';
      }
    } catch (err) {
      console.error('[App] Failed to fetch status for profile:', err);
    }
  }
  
  /**
   * Load ElevenLabs usage/quota and update the UI
   */
  async _loadElevenLabsUsage() {
    const usageEl = document.getElementById('elevenlabs-usage');
    if (!usageEl) return;
    
    try {
      const response = await fetch(`/api/tts/usage?mode=${this.socket.mode}`);
      const data = await response.json();
      
      if (data.ok && data.usage) {
        const u = data.usage;
        const usedFormatted = u.used.toLocaleString();
        const limitFormatted = u.limit.toLocaleString();
        const remainingFormatted = u.remaining.toLocaleString();
        
        // Color based on usage percentage
        let usageClass = 'usage-ok';
        if (u.percentage_used >= 90) {
          usageClass = 'usage-critical';
        } else if (u.percentage_used >= 75) {
          usageClass = 'usage-warning';
        }
        
        usageEl.innerHTML = `
          <span class="config-label">Characters</span>
          <span class="config-value ${usageClass}">
            ${usedFormatted} / ${limitFormatted} (${u.percentage_used}%)
          </span>
        `;
        
        // Add remaining info as a tooltip
        usageEl.title = `${remainingFormatted} characters remaining this month`;
      } else {
        usageEl.innerHTML = `
          <span class="config-label">Usage</span>
          <span class="config-value error">${data.error || 'Unavailable'}</span>
        `;
      }
    } catch (err) {
      console.error('[App] Failed to load ElevenLabs usage:', err);
      usageEl.innerHTML = `
        <span class="config-label">Usage</span>
        <span class="config-value error">Error loading</span>
      `;
    }
  }
  
  /**
   * Populate model dropdown based on selected provider
   */
  _populateModelDropdown(provider) {
    this._populateProviderModelDropdown('setting-llm-model', provider);
  }

  _populateCompletionGuardEvalModelDropdown(provider) {
    this._populateProviderModelDropdown('setting-completion-guard-eval-model', provider);
  }

  _populateProviderModelDropdown(selectId, provider) {
    const modelSelect = document.getElementById(selectId);
    if (!modelSelect) return;
    const models = this._settingsData?.provider_models?.[provider] || [];
    
    let html = '<option value="">Use default for provider</option>';
    for (const model of models) {
      html += `<option value="${model.id}">${model.name} (${model.context})</option>`;
    }
    modelSelect.innerHTML = html;
  }

  async _ensureProviderModelsLoaded(provider) {
    if (!provider || provider !== 'ollama') return;
    try {
      const response = await fetch(`/api/settings/models/${provider}?mode=${this.socket.mode}`);
      const data = await response.json();
      if (data.ok && Array.isArray(data.models)) {
        this._settingsData = this._settingsData || {};
        this._settingsData.provider_models = this._settingsData.provider_models || {};
        this._settingsData.provider_models[provider] = data.models;
      }
    } catch (err) {
      console.error('[App] Failed to refresh provider models:', err);
    }
  }

  _getCompletionGuardEvalProviderSelection(overrideValue = null) {
    if (this.socket.mode === 'local') return 'ollama';
    return overrideValue
      || document.getElementById('setting-completion-guard-eval-provider')?.value
      || this._settingsData?.completion_guard?.eval_provider?.default
      || 'openai';
  }

  _configureCompletionGuardEvalProviderSelect() {
    const select = document.getElementById('setting-completion-guard-eval-provider');
    if (!select) return;
    const isLocal = this.socket.mode === 'local';
    const ollamaOption = select.querySelector('option[value="ollama"]');
    if (ollamaOption) {
      ollamaOption.textContent = isLocal ? 'Ollama (Local)' : 'Ollama (Cloud)';
    }
    Array.from(select.options).forEach((option) => {
      if (!option.value) return;
      option.hidden = isLocal && option.value !== 'ollama';
      option.disabled = isLocal && option.value !== 'ollama';
    });
    if (isLocal && !select.value) {
      select.value = '';
    }
  }

  _configureProviderSelectLabels() {
    const isLocal = this.socket.mode === 'local';
    const llmSelect = document.getElementById('setting-llm-provider');
    const cgEvalSelect = document.getElementById('setting-completion-guard-eval-provider');
    const llmOllamaOption = llmSelect?.querySelector('option[value="ollama"]');
    const cgOllamaOption = cgEvalSelect?.querySelector('option[value="ollama"]');
    if (llmOllamaOption) {
      llmOllamaOption.textContent = isLocal ? 'Ollama (Local)' : 'Ollama (Cloud)';
    }
    if (cgOllamaOption) {
      cgOllamaOption.textContent = isLocal ? 'Ollama (Local)' : 'Ollama (Cloud)';
    }
  }

  _filterSelectOptions(select, allowedValues = []) {
    if (!select || !Array.isArray(allowedValues) || allowedValues.length === 0) return;
    const allowed = new Set(allowedValues);
    Array.from(select.options).forEach((option) => {
      if (!option.value) return;
      const hidden = !allowed.has(option.value);
      option.hidden = hidden;
      option.disabled = hidden;
    });
  }
  
  /**
   * Start a new chat
   */
  _startNewChat() {
    this.socket.conversationId = null;
    this.chat.clearChat();
    this._updateActiveConversation(null);
    this._updateConvIdBadge(null);
    Utils.toast('Started new chat', 'info');
  }
  
  /**
   * Load conversation history
   */
  async _loadConversationHistory() {
    const container = document.getElementById('historyList');
    
    try {
      const response = await fetch('/api/conversations?limit=100&include_archived=true');
      const data = await response.json();
      
      if (data.ok && data.conversations) {
        const convs = data.conversations;
        this._conversations = convs;
        
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
        if (this.socket.conversationId) {
          const activeConversation = convs.find(conv => conv.id === this.socket.conversationId);
          if (activeConversation?.archived) {
            this._archivedExpanded = true;
          }
        }

        container.innerHTML = this._renderConversationHistory(convs);
        this._setupHistoryTitleTooltips(container);
        this._bindConversationHistoryActions(container);
      } else {
        container.innerHTML = '<div class="history-empty">Failed to load history</div>';
      }
    } catch (err) {
      console.error('[App] Failed to load history:', err);
      container.innerHTML = `<div class="history-empty">Error: ${err.message}</div>`;
    }
  }

  _renderConversationHistory(conversations) {
    const activeConversations = conversations.filter(conv => !conv.archived);
    const archivedConversations = conversations.filter(conv => conv.archived);

    let html = activeConversations.map(conv => this._renderConversationRow(conv)).join('');

    if (archivedConversations.length > 0) {
      html += `
        <div class="history-archived-section ${this._archivedExpanded ? 'expanded' : ''}">
          <button class="history-archived-toggle" id="historyArchivedToggle" type="button">
            <span class="history-archived-chevron">${this._archivedExpanded ? '▾' : '▸'}</span>
            <span>Archived</span>
            <span class="history-archived-count">${archivedConversations.length}</span>
          </button>
          <div class="history-archived-list" style="display: ${this._archivedExpanded ? 'block' : 'none'};">
            ${archivedConversations.map(conv => this._renderConversationRow(conv)).join('')}
          </div>
        </div>
      `;
    }

    return html;
  }

  _renderConversationRow(conv) {
    const isActive = this.socket.conversationId === conv.id;
    const date = this._formatRelativeDate(conv.updated_at);
    const fullTitle = conv.title || 'Untitled';
    const archiveBadge = conv.archived ? '<span class="history-state-pill">Archived</span>' : '';
    const pinBadge = conv.pinned ? '<span class="history-pin" title="Pinned conversation">📌</span>' : '';

    return `
      <div class="history-item ${isActive ? 'active' : ''} ${conv.archived ? 'archived' : ''}"
           data-conv-id="${conv.id}"
           data-pinned="${conv.pinned ? 'true' : 'false'}"
           data-archived="${conv.archived ? 'true' : 'false'}"
           onclick="window.jarvisApp.loadConversation('${conv.id}')">
        <div class="history-item-content">
          <div class="history-title-row">
            <div class="history-title">${pinBadge}${Utils.escapeHtml(fullTitle)}</div>
            ${archiveBadge}
          </div>
          <div class="history-date">${date} · ${conv.message_count || 0} messages</div>
        </div>
        <div class="history-title-tooltip" aria-hidden="true">${Utils.escapeHtml(fullTitle)}</div>
        <div class="history-menu">
          <button class="history-menu-trigger"
                  type="button"
                  data-conv-id="${conv.id}"
                  title="Conversation options"
                  aria-label="Conversation options"
                  onclick="event.stopPropagation(); window.jarvisApp.toggleConversationMenu('${conv.id}')">☰</button>
          <div class="history-menu-dropdown" data-conv-id="${conv.id}">
            <button class="history-menu-item" type="button"
                    onclick="event.stopPropagation(); window.jarvisApp.toggleConversationPin('${conv.id}', ${conv.pinned ? 'false' : 'true'})">
              ${conv.pinned ? 'Unpin' : 'Pin'}
            </button>
            <button class="history-menu-item" type="button"
                    onclick="event.stopPropagation(); window.jarvisApp.toggleConversationArchive('${conv.id}', ${conv.archived ? 'false' : 'true'})">
              ${conv.archived ? 'Unarchive' : 'Archive'}
            </button>
            <button class="history-menu-item danger" type="button"
                    onclick="event.stopPropagation(); window.jarvisApp.deleteConversation('${conv.id}')">
              Delete
            </button>
          </div>
        </div>
      </div>
    `;
  }

  _bindConversationHistoryActions(container) {
    container.querySelector('#historyArchivedToggle')?.addEventListener('click', () => {
      this._archivedExpanded = !this._archivedExpanded;
      const archivedList = container.querySelector('.history-archived-list');
      const chevron = container.querySelector('.history-archived-chevron');
      if (archivedList) {
        archivedList.style.display = this._archivedExpanded ? 'block' : 'none';
      }
      if (chevron) {
        chevron.textContent = this._archivedExpanded ? '▾' : '▸';
      }
      container.querySelector('.history-archived-section')?.classList.toggle('expanded', this._archivedExpanded);
    });
  }

  _closeConversationMenus() {
    document.querySelectorAll('.history-menu-dropdown.open').forEach(menu => {
      menu.classList.remove('open');
      menu.closest('.history-item')?.classList.remove('menu-open');
    });
  }

  _hideConversationTooltips() {
    document.querySelectorAll('.history-title-tooltip').forEach(tooltip => {
      tooltip.style.display = 'none';
    });
  }

  toggleConversationMenu(convId) {
    const menu = document.querySelector(`.history-menu-dropdown[data-conv-id="${convId}"]`);
    if (!menu) return;
    const shouldOpen = !menu.classList.contains('open');
    this._closeConversationMenus();
    if (shouldOpen) {
      this._hideConversationTooltips();
      menu.closest('.history-item')?.classList.add('menu-open');
      menu.classList.add('open');
    }
  }

  async toggleConversationPin(convId, pinned) {
    this._closeConversationMenus();
    const ok = await this._updateConversationState(convId, { pinned });
    if (ok) {
      Utils.toast(pinned ? 'Conversation pinned' : 'Conversation unpinned', 'info');
    }
  }

  async toggleConversationArchive(convId, archived) {
    this._closeConversationMenus();
    const ok = await this._updateConversationState(convId, { archived });
    if (ok) {
      Utils.toast(archived ? 'Conversation archived' : 'Conversation restored', 'info');
    }
  }

  async _updateConversationState(convId, patch) {
    try {
      const response = await fetch(`/api/conversations/${convId}/state`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(patch)
      });
      const data = await response.json();
      if (!data.ok) {
        Utils.toast(data.error || 'Failed to update conversation', 'error');
        return false;
      }
      if (this.socket.conversationId === convId && patch.archived === true) {
        this._archivedExpanded = true;
      }
      await this._loadConversationHistory();
      return true;
    } catch (err) {
      Utils.toast(`Error: ${err.message}`, 'error');
      return false;
    }
  }
  
  /**
   * Filter conversations by title (client-side)
   */
  _filterConversations(query) {
    const container = document.getElementById('historyList');
    const items = container.querySelectorAll('.history-item');
    const lowerQuery = query.toLowerCase();
    
    items.forEach(item => {
      const title = item.querySelector('.history-title')?.textContent?.toLowerCase() || '';
      if (lowerQuery === '' || title.includes(lowerQuery)) {
        item.style.display = '';
      } else {
        item.style.display = 'none';
      }
    });

    const archivedSection = container.querySelector('.history-archived-section');
    if (archivedSection) {
      const archivedItems = archivedSection.querySelectorAll('.history-item');
      const anyVisible = Array.from(archivedItems).some(item => item.style.display !== 'none');
      archivedSection.style.display = anyVisible || lowerQuery === '' ? '' : 'none';
    }
  }
  
  /**
   * Open deep search modal
   */
  _openSearchModal() {
    const modal = document.getElementById('searchModal');
    const input = document.getElementById('deepSearchInput');
    const results = document.getElementById('searchResults');
    
    modal.classList.add('active');
    input.value = '';
    results.innerHTML = '<p class="search-hint">Enter keywords to search across all conversation messages</p>';
    input.focus();
  }
  
  /**
   * Perform deep search across all conversations
   */
  async _doDeepSearch() {
    const input = document.getElementById('deepSearchInput');
    const results = document.getElementById('searchResults');
    const query = input.value.trim();
    
    if (!query) {
      results.innerHTML = '<p class="search-hint">Please enter a search term</p>';
      return;
    }
    
    results.innerHTML = '<p class="search-hint">Searching...</p>';
    
    try {
      const response = await fetch(`/api/conversations/search?q=${encodeURIComponent(query)}`);
      const data = await response.json();
      
      if (data.ok && data.results.length > 0) {
        let html = '';
        
        for (const result of data.results) {
          html += `
            <div class="search-result-item">
              <div class="search-result-header">
                <span class="search-result-title">${Utils.escapeHtml(result.title)}</span>
                <span class="search-result-meta">${result.total_matches} match${result.total_matches > 1 ? 'es' : ''}</span>
              </div>
              <div class="search-result-matches">
          `;
          
          for (const match of result.matches) {
            const roleIcon = match.role === 'user' ? '👤' : '🤖';
            const snippet = Utils.escapeHtml(match.snippet).replace(
              new RegExp(`(${Utils.escapeHtml(query)})`, 'gi'),
              '<mark>$1</mark>'
            );
            
            html += `
              <div class="search-match">
                <div class="search-match-role">${roleIcon} ${match.role}</div>
                <div class="search-match-snippet">${snippet}</div>
              </div>
            `;
          }
          
          html += `
              </div>
              <div class="search-result-actions">
                <button class="btn btn-secondary" onclick="window.jarvisApp.loadConversation('${result.conversation_id}'); document.getElementById('searchModal').classList.remove('active');">
                  Open Conversation
                </button>
              </div>
            </div>
          `;
        }
        
        results.innerHTML = html;
      } else {
        results.innerHTML = `<p class="search-hint">No results found for "${Utils.escapeHtml(query)}"</p>`;
      }
    } catch (err) {
      console.error('[App] Search error:', err);
      results.innerHTML = `<p class="search-hint" style="color: var(--error);">Error: ${err.message}</p>`;
    }
  }
  
  /**
   * Export current conversation
   */
  _exportConversation(format) {
    const convId = this.socket.conversationId;
    
    if (!convId) {
      Utils.toast('No conversation to export', 'error');
      return;
    }
    
    // Create download link
    const url = `/api/conversations/${convId}/export?format=${format}`;
    const filename = format === 'json' ? `${convId}.json` : `${convId}.md`;
    
    // Trigger download
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    
    Utils.toast(`Exporting as ${format.toUpperCase()}...`, 'info');
    document.getElementById('exportModal').classList.remove('active');
  }
  
  /**
   * Import conversation from JSON file
   */
  async _importConversation(file) {
    if (!file.name.endsWith('.json')) {
      Utils.toast('Only JSON files can be imported', 'error');
      return;
    }
    
    try {
      const formData = new FormData();
      formData.append('file', file);
      
      const response = await fetch('/api/conversations/import', {
        method: 'POST',
        body: formData
      });
      
      const data = await response.json();
      
      if (data.ok) {
        Utils.toast(data.message || 'Conversation imported!', 'success');
        document.getElementById('exportModal').classList.remove('active');
        
        // Reload history and open the imported conversation
        await this._loadConversationHistory();
        if (data.conversation?.id) {
          this.loadConversation(data.conversation.id);
        }
      } else {
        Utils.toast(data.error || 'Import failed', 'error');
      }
    } catch (err) {
      console.error('[App] Import error:', err);
      Utils.toast(`Error: ${err.message}`, 'error');
    }
    
    // Reset file input
    document.getElementById('importFile').value = '';
  }
  
  /**
   * Clear current chat (clears messages, keeps conversation)
   */
  async _clearChat() {
    const convId = this.socket.conversationId;
    if (convId) {
      try {
        const response = await fetch(`/api/conversations/${convId}/clear`, { method: 'POST' });
        const data = await response.json();
        if (data.ok) {
          this.chat.clearChat();
          this._loadConversationHistory();
          Utils.toast('Chat cleared', 'info');
        } else {
          Utils.toast(data.error || 'Failed to clear', 'error');
        }
      } catch (err) {
        Utils.toast(`Error: ${err.message}`, 'error');
      }
    } else {
      this._startNewChat();
    }
  }
  
  /**
   * Import knowledge file (txt/md) to jarvis-intel and ingest
   */
  async _importKnowledge(file) {
    const statusEl = document.getElementById('importKnowledgeStatus');
    if (!file.name.endsWith('.md') && !file.name.endsWith('.txt')) {
      if (statusEl) statusEl.textContent = 'Only .txt or .md files allowed';
      Utils.toast('Only .txt or .md files allowed', 'error');
      return;
    }
    if (file.size > 1024 * 1024) {
      if (statusEl) statusEl.textContent = 'File too large (max 1MB)';
      Utils.toast('File too large (max 1MB)', 'error');
      return;
    }
    if (statusEl) statusEl.textContent = 'Uploading...';
    try {
      const formData = new FormData();
      formData.append('file', file);
      const response = await fetch('/api/intel/upload', {
        method: 'POST',
        body: formData
      });
      const data = await response.json();
      if (data.ok) {
        if (statusEl) statusEl.textContent = `Saved ${data.filename} – ingestion started`;
        Utils.toast(data.message || 'Knowledge imported', 'success');
        document.getElementById('importKnowledgeModal')?.classList.remove('active');
      } else {
        if (statusEl) statusEl.textContent = data.error || 'Upload failed';
        Utils.toast(data.error || 'Upload failed', 'error');
      }
    } catch (err) {
      if (statusEl) statusEl.textContent = `Error: ${err.message}`;
      Utils.toast(`Error: ${err.message}`, 'error');
    }
    document.getElementById('importKnowledgeFile').value = '';
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
    this._updateConvIdBadge(conversation.id);
    
    // Clear and rebuild chat
    this.chat.clearChat();
    
    // Calculate cumulative token usage from historical messages
    let cumulativeTokens = { input: 0, output: 0, total: 0 };
    let cumulativeCost = 0;
    
    // Add each message
    for (const msg of conversation.messages || []) {
      if (msg.role === 'user') {
        // Check if user message had an attached image
        const imageUrls = msg.data?.image_urls || (msg.data?.image_url ? [msg.data.image_url] : []);
        const imageData = imageUrls.length
          ? { images: imageUrls.map((url) => ({ url })) }
          : null;
        this.chat.addUserMessage(msg.content, imageData);
      } else if (msg.role === 'assistant') {
        // Pass as separate parameters: text, toolsUsed, data
        this.chat.addAssistantMessage(
          msg.content || '',
          msg.tools_used || [],
          msg.data || {}
        );
        
        // Sum up token usage from saved data
        const usage = msg.data?.usage;
        if (usage) {
          cumulativeTokens.input += usage.input_tokens || 0;
          cumulativeTokens.output += usage.output_tokens || 0;
          cumulativeTokens.total += usage.total_tokens || (usage.input_tokens || 0) + (usage.output_tokens || 0);
          cumulativeCost += usage.cost_usd || 0;
        }
      }
    }
    
    // Restore token counter state if we have historical data
    if (cumulativeTokens.total > 0) {
      this.chat.restoreTokenCounter(cumulativeTokens, cumulativeCost);
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
   * Update conversation ID badge in chat area
   */
  _updateConvIdBadge(convId) {
    if (!this.convIdBadge || !this.convIdText) return;
    
    if (convId) {
      this.convIdText.textContent = convId;
      this.convIdBadge.style.display = 'block';
    } else {
      this.convIdBadge.style.display = 'none';
    }
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
      const selectedMode = document.getElementById('setting-mode').value;
      const qaWordLimitRaw = document.getElementById('setting-qa-word-limit').value.trim();
      const multiTurnWordLimitRaw = document.getElementById('setting-multi-turn-word-limit').value.trim();
      const completionGuardAutoThresholdRaw = document.getElementById('setting-completion-guard-auto-threshold').value.trim();
      const ttsCheckbox = document.getElementById('setting-tts');
      const responseStyleInput = document.getElementById('setting-response-style');
      const parseNullableBool = (value) => {
        if (value === '') return null;
        return value === 'true';
      };

      // Collect all settings
      const settings = {
        mode: selectedMode,
        tts_enabled: ttsCheckbox.checked,
        progress_events: document.getElementById('setting-progress-events').checked,
        llm_provider: document.getElementById('setting-llm-provider').value || null,
        llm_model: document.getElementById('setting-llm-model').value || null,
        image_provider: document.getElementById('setting-image-provider').value || null,
        video_provider: document.getElementById('setting-video-provider').value || null,
        tts_provider: document.getElementById('setting-tts-provider').value || null,
        response_style: responseStyleInput.value || null,
        qa_word_limit: qaWordLimitRaw === '' ? null : parseInt(qaWordLimitRaw, 10),
        multi_turn_word_limit: multiTurnWordLimitRaw === '' ? null : parseInt(multiTurnWordLimitRaw, 10),
        completion_guard_enabled: parseNullableBool(document.getElementById('setting-completion-guard-enabled').value),
        completion_guard_mode: document.getElementById('setting-completion-guard-mode').value || null,
        completion_guard_ticket_on_fail: parseNullableBool(document.getElementById('setting-completion-guard-ticket-on-fail').value),
        completion_guard_show_ui_prompt: parseNullableBool(document.getElementById('setting-completion-guard-show-ui-prompt').value),
        completion_guard_include_qa: parseNullableBool(document.getElementById('setting-completion-guard-include-qa').value),
        completion_guard_include_tool_tasks: parseNullableBool(document.getElementById('setting-completion-guard-include-tool-tasks').value),
        completion_guard_auto_threshold: completionGuardAutoThresholdRaw === '' ? null : parseFloat(completionGuardAutoThresholdRaw),
        completion_guard_eval_provider: selectedMode === 'local'
          ? (document.getElementById('setting-completion-guard-eval-provider').value ? 'ollama' : null)
          : (document.getElementById('setting-completion-guard-eval-provider').value || null),
        completion_guard_eval_model: document.getElementById('setting-completion-guard-eval-model').value || null,
        history_limit: parseInt(document.getElementById('setting-history-limit').value) || 20
      };

      let saveToast = 'Settings saved!';
      if (settings.tts_enabled) {
        const defaultResponseStyle = this._settingsData?.response?.style?.default || 'auto';
        if (settings.response_style === 'detailed') {
          settings.tts_enabled = false;
          ttsCheckbox.checked = false;
          if (this.currentAudio) {
            this.stopAudioPlayback();
          }
          saveToast = 'Detailed response style selected. TTS was disabled to avoid reading long responses aloud.';
        } else if (!settings.response_style && defaultResponseStyle === 'detailed') {
          settings.response_style = 'auto';
          responseStyleInput.value = 'auto';
          saveToast = 'TTS enabled. Response style switched from detailed to auto for speech-friendly answers.';
        }
      }

      if (settings.qa_word_limit !== null && (Number.isNaN(settings.qa_word_limit) || settings.qa_word_limit < 25 || settings.qa_word_limit > 300)) {
        Utils.toast('Q&A word limit must be between 25 and 300', 'warning');
        return;
      }

      if (settings.multi_turn_word_limit !== null && (Number.isNaN(settings.multi_turn_word_limit) || settings.multi_turn_word_limit < 25 || settings.multi_turn_word_limit > 300)) {
        Utils.toast('Multi-turn word limit must be between 25 and 300', 'warning');
        return;
      }

      if (settings.completion_guard_auto_threshold !== null && (
        Number.isNaN(settings.completion_guard_auto_threshold)
        || settings.completion_guard_auto_threshold < 0.5
        || settings.completion_guard_auto_threshold > 0.99
      )) {
        Utils.toast('Completion Guard auto threshold must be between 0.50 and 0.99', 'warning');
        return;
      }
      
      // Save to server
      const response = await fetch('/api/settings/web', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(settings)
      });
      
      const result = await response.json();
      
      if (result.ok) {
        // Update mode if changed
        const newMode = selectedMode;
        if (newMode !== this.socket.mode) {
          this.socket.setMode(newMode);
          this.modeSelect.value = newMode;
          window.chatUI?._handleImageAttachmentsForMode?.(newMode, { toast: false });
        }
        
        // Update audio setting
        this.audioEnabled = settings.tts_enabled;
        Utils.storage.set('audioEnabled', this.audioEnabled);
        this._updateAudioButton();
        
        // Update glow intensity (client-side only)
        this.glowIntensity = document.getElementById('setting-glow-intensity').value;
        Utils.storage.set('glowIntensity', this.glowIntensity);
        this._applyGlowIntensity();
        
        Utils.toast(saveToast, 'success');
        this.settingsModal.classList.remove('active');

        // Refresh cached settings so image modal and other UI pick up overrides immediately
        await this._loadSettings();
        
        // Refresh token counter context window for new provider/model
        if (window.chatUI) {
          const newMode = document.getElementById('setting-mode').value;
          await window.chatUI.refreshContextWindow(newMode);
        }
      } else {
        Utils.toast(result.error || 'Failed to save settings', 'error');
      }
    } catch (err) {
      Utils.toast(`Error: ${err.message}`, 'error');
    }
  }
  
  /**
   * Reset settings to env defaults for the active mode
   */
  async _resetToDefaults() {
    if (!confirm('Reset all web overrides to the current mode env defaults?')) return;
    
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
        window.commandSystem?.refreshTools?.();
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
      window.commandSystem?.refreshTools?.();
    } catch (err) {
      Utils.toast(`Error: ${err.message}`, 'error');
    }
  }
}


// Initialize app when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
  window.jarvisApp = new JarvisApp();
});
