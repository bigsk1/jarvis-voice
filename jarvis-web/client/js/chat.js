/**
 * Jarvis Web UI - Chat Interface
 */

class ChatUI {
  constructor() {
    this.messagesContainer = document.getElementById('chatMessages');
    this.inputField = document.getElementById('chatInput');
    this.sendBtn = document.getElementById('sendBtn');
    this.micBtn = document.getElementById('micBtn');
    
    this.currentMessageId = null;
    this.pendingTools = {};
    this.isProcessing = false;
    
    // Voice recording state
    this.mediaRecorder = null;
    this.audioChunks = [];
    this.isRecording = false;
    this.recordingIndicator = null;
    
    this._setupEventListeners();
    this._setupSocketListeners();
    this._setupVoiceRecording();
  }

  /**
   * Setup DOM event listeners
   */
  _setupEventListeners() {
    // Send button
    this.sendBtn.addEventListener('click', () => this.sendMessage());
    
    // Enter to send (Shift+Enter for new line)
    this.inputField.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        this.sendMessage();
      }
    });
    
    // Auto-resize input
    this.inputField.addEventListener('input', () => {
      Utils.autoResize(this.inputField);
    });
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
      this.addToolCard(data.tool, 'pending', data.args);
    });
    
    socket.on('toolProgress', (data) => {
      this.updateToolCard(data.tool, 'pending', { progress: data.progress, status: data.status });
    });
    
    socket.on('toolComplete', (data) => {
      this.updateToolCard(data.tool, 'success', data.result, data.duration_ms);
    });
    
    socket.on('toolError', (data) => {
      this.updateToolCard(data.tool, 'error', { error: data.error });
    });
    
    socket.on('response', (data) => {
      this.hideThinking();
      this.clearStatus();  // Clear any status messages
      this.addAssistantMessage(data.text, data.tools_used, data);
      this.isProcessing = false;
      this.updateSendButton();
    });
    
    socket.on('error', (data) => {
      this.hideThinking();
      this.addErrorMessage(data.error);
      this.isProcessing = false;
      this.updateSendButton();
    });
  }

  /**
   * Send a message
   */
  sendMessage() {
    const message = this.inputField.value.trim();
    
    if (!message || this.isProcessing) return;
    
    // Add user message to UI
    this.addUserMessage(message);
    
    // Clear input
    this.inputField.value = '';
    Utils.autoResize(this.inputField);
    
    // Send via socket
    this.isProcessing = true;
    this.updateSendButton();
    this.pendingTools = {};
    
    window.jarvisSocket.sendMessage(message);
  }

  /**
   * Add user message to chat
   */
  addUserMessage(text) {
    const messageEl = document.createElement('div');
    messageEl.className = 'message user';
    messageEl.innerHTML = `
      <div class="message-bubble">
        ${Utils.escapeHtml(text)}
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
    messageEl.className = 'message assistant';
    
    // Build tool cards HTML
    let toolCardsHtml = '';
    if (toolsUsed.length > 0) {
      toolCardsHtml = '<div class="tool-cards">';
      for (const tool of toolsUsed) {
        const toolData = this.pendingTools[tool] || {};
        const toolResult = data[tool] || toolData.result || {};
        toolCardsHtml += this._createToolCardHtml(
          tool,
          toolData.status || 'success',
          toolResult,
          toolData.duration
        );
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
    if (!filename && toolsUsed.includes('generate_image')) {
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
    
    const parsedText = Utils.parseMarkdown(text);
    
    messageEl.innerHTML = `
      ${toolCardsHtml}
      ${imageHtml}
      <div class="message-bubble">
        ${parsedText}
      </div>
    `;
    
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
   * Clear status message
   */
  clearStatus() {
    // Clear pending status timeout
    if (this._statusTimeout) {
      clearTimeout(this._statusTimeout);
      this._statusTimeout = null;
    }
    
    const statusEl = this.messagesContainer.querySelector('.status-message');
    if (statusEl) {
      statusEl.remove();
    }
  }

  /**
   * Add a tool execution card
   */
  addToolCard(toolName, status, args = {}) {
    this.pendingTools[toolName] = { status, args, result: null, duration: null };
    
    const pendingCards = document.getElementById('pendingToolCards');
    if (!pendingCards) return;
    
    const cardHtml = this._createToolCardHtml(toolName, status, args);
    const cardEl = document.createElement('div');
    cardEl.innerHTML = cardHtml;
    cardEl.firstChild.id = `tool-card-${toolName}`;
    
    pendingCards.appendChild(cardEl.firstChild);
    Utils.scrollToBottom(this.messagesContainer);
  }

  /**
   * Update a tool card
   */
  updateToolCard(toolName, status, result = {}, duration = null) {
    if (this.pendingTools[toolName]) {
      this.pendingTools[toolName].status = status;
      this.pendingTools[toolName].result = result;
      this.pendingTools[toolName].duration = duration;
    }
    
    const card = document.getElementById(`tool-card-${toolName}`);
    if (!card) return;
    
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
    
    // Create a summary of the data instead of full JSON
    let summary = '';
    if (data && typeof data === 'object') {
      // Extract key info based on tool type
      if (toolName === 'generate_image') {
        summary = data.prompt ? `Prompt: "${Utils.truncate(data.prompt, 60)}"` : '';
        if (data.provider) summary += `\nProvider: ${data.provider}`;
      } else if (data.speech) {
        summary = Utils.truncate(data.speech, 100);
      } else if (data.ok !== undefined) {
        summary = data.ok ? 'Success' : 'Failed';
      } else {
        // Show truncated JSON for other tools
        summary = Utils.truncate(Utils.formatJson(data), 200);
      }
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
   * Update send button state
   */
  updateSendButton() {
    this.sendBtn.disabled = this.isProcessing;
    this.sendBtn.innerHTML = this.isProcessing ? '⏳' : '➤';
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
  }
}

// Create global instance
window.chatUI = new ChatUI();

