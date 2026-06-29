/**
 * Jarvis Web UI - WebSocket Connection
 */

class JarvisSocket {
  constructor() {
    this.socket = null;
    this.connected = false;
    this.sessionId = null;
    this.conversationId = null;
    this.mode = Utils.storage.get('mode', 'cloud');
    this.listeners = {};
  }

  /**
   * Connect to the server
   */
  connect() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host;
    
    console.log('[Socket] Connecting to server...');
    
    this.socket = io({
      transports: ['websocket', 'polling'],
      reconnection: true,
      reconnectionAttempts: 10,
      reconnectionDelay: 1000
    });

    this._setupEventHandlers();
  }

  /**
   * Setup socket event handlers
   */
  _setupEventHandlers() {
    // Connection events
    this.socket.on('connect', () => {
      console.log('[Socket] Connected');
      this.connected = true;
      this._emit('connectionChange', { connected: true });
    });

    this.socket.on('disconnect', (reason) => {
      console.log('[Socket] Disconnected:', reason);
      this.connected = false;
      this._emit('connectionChange', { connected: false, reason });
    });

    this.socket.on('connect_error', (error) => {
      console.error('[Socket] Connection error:', error);
      this._emit('connectionError', { error: error.message });
    });

    // Custom events from server
    this.socket.on('connected', (data) => {
      console.log('[Socket] Session established:', data);
      this.sessionId = data.session_id;
      this._emit('sessionReady', data);
    });

    this.socket.on('chat:thinking', (data) => {
      this._emit('thinking', data);
    });

    this.socket.on('tool:start', (data) => {
      this._emit('toolStart', data);
    });

    this.socket.on('tool:progress', (data) => {
      this._emit('toolProgress', data);
    });

    this.socket.on('tool:complete', (data) => {
      this._emit('toolComplete', data);
    });

    this.socket.on('tool:error', (data) => {
      this._emit('toolError', data);
    });

    this.socket.on('chat:response', (data) => {
      this._emit('response', data);
    });

    this.socket.on('chat:stream', (data) => {
      this._emit('stream', data);
    });

    this.socket.on('chat:error', (data) => {
      this._emit('error', data);
    });

    this.socket.on('chat:cancelled', (data) => {
      this._emit('cancelled', data);
    });

    this.socket.on('cancel:ack', (data) => {
      this._emit('cancelAck', data);
    });

    this.socket.on('chat:status', (data) => {
      this._emit('status', data);
    });

    // Feedback events (async analysis after response)
    this.socket.on('feedback:start', (data) => {
      this._emit('feedbackStart', data);
    });
    
    this.socket.on('feedback:complete', (data) => {
      this._emit('feedbackComplete', data);
    });

    this.socket.on('completion_guard:updated', (data) => {
      this._emit('completionGuardUpdated', data);
    });

    this.socket.on('completion_guard:ticket_created', (data) => {
      this._emit('completionGuardTicketCreated', data);
    });

    this.socket.on('completion_guard:error', (data) => {
      this._emit('completionGuardError', data);
    });

    this.socket.on('mode:changed', (data) => {
      this.mode = data.mode;
      Utils.storage.set('mode', data.mode);
      this._emit('modeChanged', data);
    });

    this.socket.on('tools:updated', (data) => {
      this._emit('toolsUpdated', data);
    });

    // Proactive notifications keep their Socket.IO event names because the
    // ProactiveManager subscribes to them through this wrapper. Without these
    // pass-through handlers, the server events reach Socket.IO but never reach
    // the browser notification, reminder TTS, badge, or acknowledgment UI.
    [
      'proactive:counts',
      'proactive:alert',
      'proactive:reminder',
      'proactive:ack_success',
      'proactive:error'
    ].forEach((event) => {
      this.socket.on(event, (data) => {
        this._emit(event, data);
      });
    });
    
    // Conversation events
    this.socket.on('conversation:created', (data) => {
      this.conversationId = data.conversation_id;
      this._emit('conversationCreated', data);
    });
    
    this.socket.on('conversation:loaded', (data) => {
      if (data.conversation) {
        this.conversationId = data.conversation.id;
      }
      this._emit('conversationLoaded', data);
    });
  }

  /**
   * Send a chat message (with optional image, prompt metadata, and text file)
   * @param {string} message - The message text
   * @param {Object} imageData - Optional image payload {action, settings, images: [{url, filename}]}
   * @param {Object} promptMeta - Optional prompt metadata {system_instruction, prompt_name, tool_hints}
   * @param {boolean} requestFeedback - Whether to request feedback analysis after response
   * @param {Object} fileContext - Optional text file data {name, content, size, type}
   */
  sendMessage(message, imageData = null, promptMeta = null, requestFeedback = false, fileContext = null) {
    if (!this.connected) {
      console.error('[Socket] Not connected');
      return false;
    }

    const payload = {
      message,
      mode: this.mode,
      conversation_id: this.conversationId
    };
    
    // Include image data if provided
    if (imageData) {
      payload.image = imageData;
    }
    
    // Include text file context if provided
    if (fileContext) {
      payload.file_context = {
        name: fileContext.name,
        content: fileContext.content,
        size: fileContext.size
      };
    }
    
    // Include prompt metadata if provided (workflows are handled by orchestrator via /trigger)
    if (promptMeta) {
      if (promptMeta.system_instruction) {
        payload.system_instruction = promptMeta.system_instruction;
      }
      if (promptMeta.prompt_name) {
        payload.prompt_name = promptMeta.prompt_name;
      }
      if (Array.isArray(promptMeta.tool_hints) && promptMeta.tool_hints.length > 0) {
        payload.tool_hints = promptMeta.tool_hints;
      }
    }
    
    // Include feedback request if enabled
    if (requestFeedback) {
      payload.request_feedback = true;
    }

    this.socket.emit('chat:send', payload);

    return true;
  }
  
  /**
   * Emit raw event to server
   */
  emit(event, data) {
    if (this.connected) {
      this.socket.emit(event, data);
    }
  }

  /**
   * Cancel current processing
   */
  cancel(conversationId) {
    if (this.connected) {
      this.socket.emit('chat:cancel', { conversation_id: conversationId });
    }
  }

  /**
   * Set mode (cloud/local)
   */
  setMode(mode) {
    if (this.connected) {
      this.socket.emit('mode:set', { mode });
    }
    this.mode = mode;
    Utils.storage.set('mode', mode);
  }

  /**
   * Refresh tools list
   */
  refreshTools() {
    if (this.connected) {
      this.socket.emit('tools:refresh');
    }
  }

  /**
   * Register event listener
   */
  on(event, callback) {
    if (!this.listeners[event]) {
      this.listeners[event] = [];
    }
    this.listeners[event].push(callback);
  }

  /**
   * Remove event listener
   */
  off(event, callback) {
    if (this.listeners[event]) {
      this.listeners[event] = this.listeners[event].filter(cb => cb !== callback);
    }
  }

  /**
   * Emit event to listeners
   */
  _emit(event, data) {
    if (this.listeners[event]) {
      this.listeners[event].forEach(callback => callback(data));
    }
  }

  /**
   * Disconnect from server
   */
  disconnect() {
    if (this.socket) {
      this.socket.disconnect();
    }
  }
}

// Create global instance
window.jarvisSocket = new JarvisSocket();
