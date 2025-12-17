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
    
    this._setupEventListeners();
    this._setupSocketListeners();
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

