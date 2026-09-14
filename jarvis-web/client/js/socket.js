/**
 * Jarvis Web UI - WebSocket Connection
 */

class JarvisSocket {
  constructor() {
    this.socket = null;
    this.connected = false;
    this.sessionId = null;
    this._conversationId = null;
    this.mode = Utils.storage.get('mode', 'cloud');
    this.listeners = {};
    this.completedResponses = new Set();
    this.pendingRequestId = null;
    try {
      this.conversationId = window.sessionStorage.getItem('jarvis.activeConversation') || null;
      this.pendingRequestId = window.sessionStorage.getItem('jarvis.pendingRequest') || null;
    } catch (_) { /* Storage is optional in restricted browsers. */ }
  }

  get conversationId() { return this._conversationId || null; }

  set conversationId(value) {
    this._conversationId = value || null;
    try {
      if (value) window.sessionStorage.setItem('jarvis.activeConversation', value);
      else window.sessionStorage.removeItem('jarvis.activeConversation');
    } catch (_) { /* The live connection still works without session storage. */ }
  }

  rememberResponse(messageId) {
    if (!messageId) return;
    this.completedResponses.add(messageId);
    if (this.completedResponses.size > 500) {
      this.completedResponses.delete(this.completedResponses.values().next().value);
    }
  }

  clearPendingRequest() {
    this.pendingRequestId = null;
    try { window.sessionStorage.removeItem('jarvis.pendingRequest'); } catch (_) { /* Optional. */ }
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
      reconnectionAttempts: Infinity,
      reconnectionDelay: 1000,
      // Socket.IO invokes this again on reconnect, so a renewed login is used.
      auth: (callback) => {
        let token = null;
        try { token = Utils.auth.getToken(); } catch (_) { /* Cookie fallback. */ }
        callback(token ? { token } : {});
      }
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
      if (error.data?.code === 'authentication_required') this._requireLogin();
    });

    this.socket.on('auth:required', () => this._requireLogin());

    // Custom events from server
    this.socket.on('connected', (data) => {
      console.log('[Socket] Session established:', data);
      // Socket.IO drains buffered server events before its connect callback.
      // Session-ready listeners must already be able to load/resume the thread.
      this.connected = true;
      this.sessionId = data.session_id;
      this._emit('sessionReady', data);
    });

    this.socket.on('chat:thinking', (data) => {
      if (data.message_id === this.pendingRequestId) this.clearPendingRequest();
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

    this.socket.on('chat:run', (data) => this._emit('runState', data));
    this.socket.on('chat:rejected', (data) => this._emit('rejected', data));
    this.socket.on('chat:resume_missing', (data) => this._emit('resumeMissing', data));

    this.socket.on('chat:status', (data) => {
      this._emit('status', data);
    });

    this.socket.on('embedding:status', (data) => {
      this._emit('embeddingStatus', data);
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

    this.socket.on('message_reaction:updated', (data) => {
      this._emit('messageReactionUpdated', data);
    });

    this.socket.on('message_reaction:error', (data) => {
      this._emit('messageReactionError', data);
    });

    this.socket.on('mode:changed', (data) => {
      this.mode = data.mode;
      Utils.storage.set('mode', data.mode);
      this._emit('modeChanged', data);
    });
    this.socket.on('mode:rejected', (data) => this._emit('modeRejected', data));

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
        if ((data.conversation.messages || []).some(msg => msg.data?._request_id === this.pendingRequestId)) {
          this.clearPendingRequest();
        }
      }
      this._emit('conversationLoaded', data);
    });
  }

  _requireLogin() {
    // Keep pending request/conversation IDs for recovery after sign-in.
    this.socket.disconnect();
    try { Utils.auth.clearToken(); } catch (_) { /* Storage may be unavailable. */ }
    window.location.href = `/login?redirect=${encodeURIComponent(window.location.pathname)}`;
  }

  /**
   * Send a chat message (with optional image, prompt metadata, and text file)
   * @param {string} message - The message text
   * @param {Object} imageData - Optional image payload {action, settings, images: [{url, filename}]}
   * @param {Object} promptMeta - Optional prompt metadata {system_instruction, prompt_name, tool_hints, tool_policy, request_kind, tool_rag_limit}
   * @param {boolean} requestFeedback - Whether to request feedback analysis after response
   * @param {Object} fileContext - Legacy inline text context; new text files use attachments.
   * @param {Array} attachments - Ordered server-issued PDF/audio/text source metadata
   */
  sendMessage(
    message,
    imageData = null,
    promptMeta = null,
    requestFeedback = false,
    fileContext = null,
    attachments = null
  ) {
    if (!this.connected) {
      console.error('[Socket] Not connected');
      return false;
    }

    const payload = {
      message,
      mode: this.mode,
      conversation_id: this.conversationId,
      request_id: typeof crypto.randomUUID === 'function'
        ? crypto.randomUUID()
        : 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (char) => {
            const value = crypto.getRandomValues(new Uint8Array(1))[0] & 15;
            return (char === 'x' ? value : (value & 3) | 8).toString(16);
          })
    };
    this.lastRequestId = payload.request_id;
    this.pendingRequestId = payload.request_id;
    try { window.sessionStorage.setItem('jarvis.pendingRequest', payload.request_id); } catch (_) { /* Optional. */ }
    
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

    if (Array.isArray(attachments) && attachments.length > 0) {
      payload.attachments = attachments;
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
      if (promptMeta.tool_policy === 'none') {
        payload.tool_policy = 'none';
      }
      if (promptMeta.request_kind === 'canvas_export') {
        payload.request_kind = promptMeta.request_kind;
      }
      if (Number.isInteger(promptMeta.tool_rag_limit) && promptMeta.tool_rag_limit > 0) {
        payload.tool_rag_limit = promptMeta.tool_rag_limit;
      }
    }
    
    // Include feedback request if enabled
    if (requestFeedback && promptMeta?.tool_policy !== 'none') {
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
  cancel(conversationId, messageId) {
    if (this.connected) {
      this.socket.emit('chat:cancel', { conversation_id: conversationId, message_id: messageId });
      return true;
    }
    return false;
  }

  /**
   * Set mode (cloud/local)
   */
  setMode(mode) {
    if (this.connected) {
      this.socket.emit('mode:set', { mode });
    }
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
    if (event === 'error' && data?.admitted === false && data.message_id === this.pendingRequestId) {
      this.clearPendingRequest();
      this._emit('rejected', data);
      return;
    }
    const pendingLoad = window.jarvisApp?._pendingConversationLoad;
    if (event === 'error' && !data?.message_id && pendingLoad
        && (!pendingLoad.id || !data?.conversation_id || pendingLoad.id === data.conversation_id)) {
      this._emit('conversationLoadError', data);
      return;
    }
    const scoped = new Set([
      'thinking', 'toolStart', 'toolProgress', 'toolComplete', 'toolError', 'response',
      'stream', 'error', 'cancelled', 'cancelAck', 'status', 'runState', 'rejected',
      'feedbackStart', 'feedbackComplete', 'completionGuardUpdated',
      'completionGuardTicketCreated', 'completionGuardError'
    ]);
    if (scoped.has(event) && data?.conversation_id && data.conversation_id !== this.conversationId) return;
    if (['response', 'error', 'cancelled'].includes(event)) {
      if (this.completedResponses.has(data?.message_id)) return;
      this.rememberResponse(data?.message_id);
    } else if (['thinking', 'toolStart', 'toolProgress', 'toolComplete', 'toolError', 'stream', 'status'].includes(event)
        && this.completedResponses.has(data?.message_id)) {
      return;
    }
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
