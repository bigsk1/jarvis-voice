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
        if (e.target.closest('.conversation-item') && window.innerWidth <= 768) {
          sidebar.classList.remove('mobile-open');
          document.body.classList.remove('sidebar-open');
        }
      });
    }
    
    // Mode selector
    this.modeSelect.addEventListener('change', async (e) => {
      const newMode = e.target.value;
      this.socket.setMode(newMode);
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
      
      // Sync to server so TTS generation is actually disabled (saves 11labs tokens!)
      try {
        await fetch('/api/settings/web', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ tts_enabled: this.audioEnabled })
        });
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
      const response = await fetch('/api/settings');
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
        
        // Populate Video Provider
        const videoSelect = document.getElementById('setting-video-provider');
        videoSelect.value = s.video?.provider?.is_override ? s.video.provider.value : '';
        const videoDefault = document.getElementById('video-provider-default');
        videoDefault.textContent = `(${envFile}: ${s.video?.provider?.default || 'xai'})`;
        videoDefault.className = s.video?.provider?.is_override ? 'setting-default setting-override' : 'setting-default';
        if (s.video?.provider?.is_override) {
          videoDefault.textContent = `⚡ override: ${s.video.provider.value}`;
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
              <span class="config-value">${c.TTS_VOICE || c.QWEN3_TTS_VOICE || '(default)'}</span>
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
            <div class="config-item" id="elevenlabs-usage">
              <span class="config-label">Usage</span>
              <span class="config-value loading">Loading...</span>
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
              <span class="config-label">Mode</span>
              <span class="config-value">${data.mode}</span>
            </div>
          </div>
        `;
        
        // Fetch ElevenLabs usage if in cloud mode
        if (!isLocal && c.TTS_PROVIDER === 'elevenlabs') {
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
    this._updateConvIdBadge(null);
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
                 title="${conv.id}"
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
        
        // Store conversations for filtering
        this._conversations = data.conversations;
      } else {
        container.innerHTML = '<div class="history-empty">Failed to load history</div>';
      }
    } catch (err) {
      console.error('[App] Failed to load history:', err);
      container.innerHTML = `<div class="history-empty">Error: ${err.message}</div>`;
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
        const imageData = msg.data && msg.data.image_url 
          ? { url: msg.data.image_url } 
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
      // Collect all settings
      const settings = {
        tts_enabled: document.getElementById('setting-tts').checked,
        progress_events: document.getElementById('setting-progress-events').checked,
        llm_provider: document.getElementById('setting-llm-provider').value || null,
        llm_model: document.getElementById('setting-llm-model').value || null,
        image_provider: document.getElementById('setting-image-provider').value || null,
        video_provider: document.getElementById('setting-video-provider').value || null,
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
        
        // Update glow intensity (client-side only)
        this.glowIntensity = document.getElementById('setting-glow-intensity').value;
        Utils.storage.set('glowIntensity', this.glowIntensity);
        this._applyGlowIntensity();
        
        Utils.toast('Settings saved!', 'success');
        this.settingsModal.classList.remove('active');
        
        // Refresh token counter context window for new provider/model
        if (window.chatUI) {
          const newMode = document.getElementById('setting-mode').value;
          await window.chatUI.refreshContextWindow(newMode);
        }
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

