/** One ephemeral Talk owner; credentials and HTTP stay in the background. */
export class TalkBridge {
  constructor(client, enqueue, broadcast) {
    Object.assign(this, {client, enqueue, broadcast});
    this.owner = null;
    this.pendingCancel = null;
    this.ports = new Map();
  }

  attach(port) {
    this.ports.set(port, new Set());
    this.post(port, {type: 'talk:owner', sessionId: this.owner?.id || null});
  }

  post(port, message) { try { port.postMessage(message); } catch { this.detach(port); } }

  detach(port) {
    this.ports.delete(port);
    if (this.owner?.port === port) this.release('Talk ended because its window closed.');
  }

  requireIdle() {
    if (this.owner) throw new Error('End Talk in its window before changing the conversation or sending another message.');
  }

  current(owner) {
    const {client} = this;
    return this.owner === owner && this.ports.has(owner.port) && client.transport === owner.transport &&
      client.authScope === owner.authScope && client.state.mode === owner.mode &&
      client.state.settings.serverUrl === owner.serverUrl &&
      client.state.conversationId === owner.conversationId &&
      !['disconnected', 'error', 'auth_required', 'unconfigured'].includes(client.state.connection.status);
  }

  observe(state) {
    const pending = this.pendingCancel;
    if (pending) {
      if (this.client.transport !== pending.transport || this.client.authScope !== pending.authScope ||
          state.run?.messageId === pending.id && ['completed', 'failed', 'cancelled'].includes(state.run.status)) {
        this.pendingCancel = null;
      } else if (state.run?.messageId === pending.id && state.run.conversationId && state.run.status === 'running') {
        this.pendingCancel = null;
        void this.client.cancel().catch(() => {});
      }
    }
    const owner = this.owner;
    if (!owner) return;
    // The server creates the first conversation after accepting our first turn.
    if (!owner.conversationId && owner.turn && state.run?.messageId === owner.turn) {
      owner.conversationId = state.conversationId;
    }
    if (!this.current(owner)) this.release('Talk ended because the connection, mode, or conversation changed.');
    else if (owner.cancelRequested && state.run?.messageId === owner.turn && state.run.conversationId &&
        this.client.isActive() && !['sending', 'stopping'].includes(state.run.status)) {
      owner.cancelRequested = false;
      void this.client.cancel().catch(error => this.post(owner.port, {type: 'talk:event', sessionId: owner.id,
        event: 'chat:error', data: {message_id: owner.turn, error: error.message}}));
    }
  }

  event(event, data) {
    const owner = this.owner;
    if (!owner || !this.current(owner)) return;
    if (data.conversation_id && data.conversation_id !== owner.conversationId) return;
    if (!['chat:response', 'chat:run', 'chat:error', 'chat:cancelled', 'chat:rejected'].includes(event)) return;
    if (event === 'chat:response' && data.message_id === owner.turn) {
      owner.answer = {speech: String(data.speech || '').slice(0, 12001), audio_url: String(data.audio_url || '').slice(0, 2000)};
    }
    if (data.message_id === owner.turn && (event === 'chat:run' && !['running', 'stopping'].includes(data.status) ||
        ['chat:rejected', 'chat:cancelled'].includes(event) || event === 'chat:error' && data.admitted === false)) owner.settled = true;
    this.post(owner.port, {type: 'talk:event', sessionId: owner.id, event,
      data: {message_id: data.message_id, conversation_id: data.conversation_id, status: data.status,
        ok: data.ok, cancelled: data.cancelled, error: data.error, admitted: data.admitted,
        run_status: data.run_status,
        approval_outcome: data.approval_outcome,
        ...(event === 'chat:response' && data.message_id === owner.turn ? owner.answer : {})}});
  }

  release(reason = '', cancel = false) {
    const owner = this.owner;
    if (!owner) return;
    this.owner = null;
    owner.request?.controller.abort();
    if (cancel && owner.turn && !owner.settled && this.client.state.run?.messageId === owner.turn) {
      this.pendingCancel = {id: owner.turn, transport: owner.transport, authScope: owner.authScope};
      this.observe(this.client.state);
    }
    this.post(owner.port, {type: 'talk:ended', sessionId: owner.id, reason});
    this.broadcast({type: 'talk:owner', sessionId: null});
  }

  handle(port, message) {
    if (!this.ports.has(port) || message?.type !== 'talk:request') return;
    const {action, sessionId, id, payload = {}} = message;
    if (typeof sessionId !== 'string' || !/^[a-zA-Z0-9-]{1,80}$/.test(sessionId) || typeof id !== 'string' || id.length > 100) return;
    const closed = this.ports.get(port);
    if (action === 'release') {
      closed.add(sessionId);
      if (closed.size > 100) closed.delete(closed.values().next().value);
      if (this.owner?.port === port && this.owner.id === sessionId) this.release('', payload.cancel === true);
      return;
    }
    if (action === 'abort') {
      const request = this.owner?.port === port && this.owner.id === sessionId && this.owner.request;
      if (request?.id === payload.id) { request.controller.abort(); this.owner.request = null; }
      return;
    }
    const run = async () => {
      if (!this.ports.has(port) || closed.has(sessionId)) throw new Error('Talk ended.');
      if (action === 'claim') {
        this.requireIdle();
        this.client.requireIdle();
        if (this.client.state.connection.status !== 'connected' || !this.client.state.capabilities?.talk) {
          throw new Error('Connect to an updated Jarvis Web server to use Talk.');
        }
        const draft = this.client.state.draft;
        if (draft.text?.trim() || draft.attachment || draft.context || draft.page || draft.pageLink) {
          throw new Error('Send or clear your draft and attachments before starting Talk.');
        }
        this.owner = {id: sessionId, port, transport: this.client.transport, authScope: this.client.authScope,
          serverUrl: this.client.state.settings.serverUrl, mode: this.client.state.mode,
          conversationId: this.client.state.conversationId, turn: null, settled: true, answer: null, request: null};
        this.broadcast({type: 'talk:owner', sessionId});
        return;
      }
      const owner = this.owner;
      if (!owner || owner.id !== sessionId || owner.port !== port || !this.current(owner)) throw new Error('Talk ended.');
      if (action === 'send') {
        if (!owner.settled) throw new Error('Wait for the previous task to finish.');
        if (typeof payload.text !== 'string' || !payload.text.trim() || payload.text.length > 32000 ||
            typeof payload.requestId !== 'string' || !/^[0-9a-f-]{36}$/i.test(payload.requestId)) throw new Error('Invalid spoken message.');
        owner.turn = payload.requestId; owner.settled = false; owner.answer = null;
        try {
          return await this.client.send(payload.text, {inputMode: 'talk', requestId: owner.turn, isCurrent: () => this.current(owner)});
        } catch (error) { owner.settled = true; throw error; }
      }
      if (action === 'cancel') {
        if (owner.turn && !owner.settled) {
          if (this.client.state.run?.messageId === owner.turn && this.client.state.run.conversationId &&
              this.client.isActive() && this.client.state.run.status !== 'sending') return this.client.cancel();
          // The request can still be crossing admission, especially in a new chat.
          owner.cancelRequested = true;
        }
        return;
      }
      if (owner.request) throw new Error('Wait for the speech request to finish.');
      const request = {id, controller: new AbortController()};
      owner.request = request;
      try {
        let result;
        if (action === 'stt') {
          if (!owner.settled || this.client.isActive()) throw new Error('Wait for the current task to finish.');
          result = await owner.transport.transcribe(payload.bytes, payload.mimeType, owner.mode, request.controller.signal);
        } else if (action === 'tts') {
          if (!owner.answer || payload.messageId !== owner.turn || !owner.answer.speech.includes(payload.text)) throw new Error('This reply no longer belongs to Talk.');
          result = await owner.transport.synthesize(payload.text, owner.mode, owner.turn, request.controller.signal);
        } else if (action === 'audio') {
          if (!owner.answer?.audio_url || payload.messageId !== owner.turn) throw new Error('This reply no longer belongs to Talk.');
          result = await owner.transport.speech(owner.answer.audio_url, {audio: true, signal: request.controller.signal});
        } else throw new Error('Unknown Talk action.');
        if (!this.current(owner) || request.controller.signal.aborted) throw new Error('Talk ended.');
        return result;
      } finally { if (owner.request === request) owner.request = null; }
    };
    // Speech HTTP never holds the command queue: Pause/End must abort immediately.
    const result = ['claim', 'send'].includes(action) ? this.enqueue(run) : Promise.resolve().then(run);
    void result.then(value => this.post(port, {type: 'talk:reply', sessionId, id, ok: true, value}),
      error => this.post(port, {type: 'talk:reply', sessionId, id, ok: false, error: error.message || 'Speech request failed.'}));
  }
}
