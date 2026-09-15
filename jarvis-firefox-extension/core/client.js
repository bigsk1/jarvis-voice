import {normalizeServerUrl, originPermission, assertCapabilities} from './connection.js';
import {initialState, checkpointState, savedMessages, publicRun, ACTIVE_STATUSES, normalizePreferences, submittedRequests, mergeImageStageText} from './state.js';
import {JarvisTransport} from './transport.js';

const SESSION_KEY = 'jarvisSession';
const SETTINGS_KEY = 'jarvisSettings';
const DEFAULT_PROMPT = 'Analyze this screenshot. Explain what is visible and highlight relevant errors or useful next steps.';

/** Browser-independent application client; background.js is its only owner. */
export class JarvisClient {
  constructor({storage, permissions, ioFactory, fetchImpl, onState = () => {}, uuid = () => crypto.randomUUID()}) {
    Object.assign(this, {storage, permissions, ioFactory, fetchImpl, onState, uuid});
    this.state = initialState();
    this.token = '';
    this.pendingRequestId = null;
    this.transport = null;
    this.connectPromise = null;
    this.intent = false;
    this.writeQueue = Promise.resolve();
    this.recoveryTimer = null;
    this.restoringConversation = null;
    this.uploading = false;
    this.generation = 0;
    this.pendingDraft = null;
    this.modeTimer = null;
    this.authScope = crypto.randomUUID();
  }

  async restore() {
    const [local, session] = await Promise.all([
      this.storage.local.get(SETTINGS_KEY), this.storage.session.get(SESSION_KEY),
    ]);
    const settings = local[SETTINGS_KEY] || {};
    this.state = initialState(settings);
    const saved = session[SESSION_KEY];
    if (saved && saved.serverUrl === settings.serverUrl) {
      this.state = {...this.state, ...saved.state, settings: this.state.settings};
      this.token = typeof saved.token === 'string' ? saved.token : '';
      this.pendingRequestId = saved.pendingRequestId || null;
      this.pendingDraft = saved.pendingDraft || null;
      this.intent = saved.intent === true;
      if (typeof saved.authScope === 'string' && saved.authScope.length <= 150) this.authScope = saved.authScope;
    }
    this.state.submittedRequests = submittedRequests(this.state.submittedRequests);
    this.state.connection = {
      status: settings.serverUrl ? 'disconnected' : 'unconfigured',
      authRequired: this.state.connection.authRequired === true, error: null,
    };
    this.state.pendingMode = null;
    if (this.state.run?.status === 'sending' || this.pendingRequestId) {
      this.state.run = {...this.state.run, status: 'recovering'};
    }
    this.publish();
    return this.state;
  }

  publish() { this.onState(structuredClone(this.state)); }

  async checkpoint() {
    const record = structuredClone({
      serverUrl: this.state.settings.serverUrl, token: this.token, authScope: this.authScope,
      pendingRequestId: this.pendingRequestId, pendingDraft: this.pendingDraft, intent: this.intent,
      state: checkpointState(this.state),
    });
    const write = this.writeQueue.catch(() => {}).then(() => this.storage.session.set({[SESSION_KEY]: record}));
    this.writeQueue = write;
    return write;
  }

  changed() {
    this.publish();
    this.checkpoint().catch(() => {
      this.state.notice = 'Firefox could not save session recovery state. Reopen the saved conversation if the extension restarts.';
      this.publish();
    });
  }

  isActive() { return ACTIVE_STATUSES.has(this.state.run?.status); }

  requireIdle() {
    if (this.isActive() || this.uploading || this.state.pendingMode || this.state.connection.status === 'recovering') {
      throw new Error('Wait for the current request to finish, or stop it and wait before changing the conversation.');
    }
  }

  async configure(settings) {
    this.requireIdle();
    const preferences = this.state.settings.preferences;
    const serverUrl = normalizeServerUrl(settings.serverUrl, settings);
    const generation = ++this.generation;
    if (!await this.permissions.contains({origins: [originPermission(serverUrl)]})) {
      throw new Error('Allow Firefox to connect to this server in Settings first.');
    }
    if (generation !== this.generation) return;
    if (this.state.settings.serverUrl !== serverUrl) {
      this.close();
      this.token = '';
      this.pendingRequestId = null;
      this.pendingDraft = null;
      this.intent = false;
      this.state = initialState();
      this.rotateAuthScope();
    }
    this.state.settings = {serverUrl, allowInsecureLocal: settings.allowInsecureLocal === true, preferences};
    await this.storage.local.set({[SETTINGS_KEY]: this.state.settings});
    if (this.state.connection.status === 'unconfigured') this.state.connection.status = 'disconnected';
    await this.checkpoint();
    this.publish();
  }

  async updatePreferences(preferences) {
    const current = normalizePreferences(this.state.settings.preferences);
    for (const key of Object.keys(current)) {
      if (typeof preferences?.[key] === 'boolean') current[key] = preferences[key];
    }
    this.state.settings.preferences = current;
    await this.storage.local.set({[SETTINGS_KEY]: this.state.settings});
    await this.checkpoint();
    this.publish();
  }

  rotateAuthScope() {
    this.authScope = crypto.randomUUID();
    this.state.submittedRequests = [];
  }

  updateSubmittedRequest(requestId, values) {
    const request = this.state.submittedRequests.find(item => item.requestId === requestId);
    if (request) Object.assign(request, values);
  }

  close() {
    this.generation++;
    this.connectPromise = null;
    clearTimeout(this.recoveryTimer);
    clearTimeout(this.modeTimer);
    this.state.pendingMode = null;
    this.recoveryTimer = null;
    this.restoringConversation = null;
    this.transport?.close();
    this.transport = null;
  }

  async connect() {
    if (this.connectPromise) return this.connectPromise;
    if (['connected', 'recovering'].includes(this.state.connection.status) && this.transport?.socket?.connected) return;
    const promise = this.connectChecked();
    this.connectPromise = promise;
    try { await promise; }
    finally { if (this.connectPromise === promise) this.connectPromise = null; }
  }

  async connectChecked() {
    const serverUrl = normalizeServerUrl(this.state.settings.serverUrl, this.state.settings);
    const generation = this.generation;
    if (!await this.permissions.contains({origins: [originPermission(serverUrl)]})) {
      throw new Error('Firefox permission for this server was removed. Save the connection in Settings again.');
    }
    if (generation !== this.generation) return;
    this.close();
    this.state.connection = {...this.state.connection, status: 'connecting', error: null};
    this.publish();
    const transport = new JarvisTransport({
      serverUrl, token: this.token, ioFactory: this.ioFactory, fetchImpl: this.fetchImpl,
      onUnauthorized: () => { if (this.transport === transport) this.unauthorized(); },
    });
    this.transport = transport;
    try {
      const status = await transport.status();
      if (this.transport !== transport) return;
      assertCapabilities(status);
      this.state.connection.authRequired = status.features.auth;
      if (status.features.auth && !this.token) {
        this.state.connection.status = 'auth_required';
        this.changed();
        return;
      }
      this.intent = true;
      this.openSocket(transport);
      this.changed();
    } catch (error) {
      if (this.transport === transport) {
        this.state.connection.status = 'error';
        this.state.connection.error = error.message;
        this.close();
        this.changed();
      }
      throw error;
    }
  }

  async login(password) {
    if (typeof password !== 'string' || !password) throw new Error('Enter your Jarvis Web password.');
    if (!this.transport) await this.connect();
    const transport = this.transport;
    if (!transport || this.state.connection.status === 'error') throw new Error('Check the server connection before signing in.');
    const result = await transport.login(password);
    if (this.transport !== transport) return;
    if (typeof result.token !== 'string' || !result.token) throw new Error('The server did not return a login token.');
    this.rotateAuthScope();
    this.token = result.token;
    this.intent = true;
    await this.checkpoint();
    if (this.transport !== transport) return;
    transport.token = this.token;
    this.state.connection = {...this.state.connection, status: 'connecting', error: null};
    this.openSocket(transport);
    this.publish();
  }

  async logout() {
    this.close();
    this.rotateAuthScope();
    this.token = '';
    this.intent = false;
    // Server work may continue. Retain its identifiers for recovery after login.
    this.state.connection = {...this.state.connection,
      status: this.state.connection.authRequired ? 'auth_required' : 'disconnected', error: null};
    this.state.notice = this.isActive() ? 'Disconnected. Jarvis continues the accepted request; reconnect to recover it.' : 'Disconnected from Jarvis.';
    await this.checkpoint();
    this.publish();
  }

  unauthorized() {
    this.close();
    this.rotateAuthScope();
    this.token = '';
    this.state.connection = {status: 'auth_required', authRequired: true, error: 'Sign in again to continue.'};
    this.changed();
  }

  openSocket(transport) {
    const handle = event => data => {
      if (this.transport !== transport) return;
      try { this.onEvent(event, data || {}); }
      catch (error) { this.state.notice = error.message; this.changed(); }
    };
    const names = ['connected', 'disconnect', 'connect_error', 'auth:expired', 'auth:error', 'auth:required',
      'conversation:created', 'conversation:loaded', 'chat:thinking', 'chat:run', 'chat:status',
      'chat:response', 'chat:error', 'chat:cancelled', 'chat:rejected', 'chat:resume_missing',
      'tool:start', 'tool:progress', 'tool:complete', 'tool:error', 'cancel:ack', 'mode:changed', 'mode:rejected'];
    transport.open(Object.fromEntries(names.map(event => [event, handle(event)])));
  }

  armRecoveryTimeout() {
    clearTimeout(this.recoveryTimer);
    this.recoveryTimer = setTimeout(() => {
      this.state.connection.status = 'error';
      this.state.connection.error = 'Jarvis did not confirm recovery. Reconnect to check the existing request; no work was resent.';
      this.close();
      this.changed();
    }, 20000);
    this.recoveryTimer.unref?.();
  }

  recover() {
    if (this.pendingRequestId) {
      this.state.connection.status = 'recovering';
      this.armRecoveryTimeout();
      this.transport.emit('chat:resume', {request_id: this.pendingRequestId});
    } else if (this.state.conversationId) {
      this.state.connection.status = 'recovering';
      this.restoringConversation = this.state.conversationId;
      this.armRecoveryTimeout();
      this.transport.emit('conversation:load', {conversation_id: this.state.conversationId, reconnect_only: true});
    }
  }

  eventBelongs(event, data) {
    if (data.conversation_id && this.state.conversationId && data.conversation_id !== this.state.conversationId) return false;
    const id = data.message_id;
    const current = this.pendingRequestId || this.state.run?.messageId;
    if (!id || id === current) {
      return !(id && !this.pendingRequestId && this.state.run && !this.isActive() &&
        (event === 'chat:thinking' || event === 'chat:run' && ACTIVE_STATUSES.has(data.status)));
    }
    if (this.pendingRequestId || this.isActive()) return false;
    if (this.state.messages.some(message => message.id === `assistant-${id}` || message.id === `user-${id}`)) return false;
    // Another client may start a new turn in the subscribed conversation.
    return event === 'chat:thinking' || event === 'chat:run' && ACTIVE_STATUSES.has(data.status);
  }

  restorePendingDraft() {
    if (this.pendingDraft) {
      const draft = this.state.draft;
      if (!draft.text && !draft.attachment && !draft.context || this.isSubmittedDraft()) {
        this.state.draft = this.pendingDraft;
        this.state.messages = this.state.messages.filter(message => message.id !== `user-${this.pendingRequestId}`);
      } else {
        // Keep subsequent typing and visibly distinguish the rejected local
        // bubble from a message that reached the saved server conversation.
        const bubble = this.state.messages.find(message => message.id === `user-${this.pendingRequestId}`);
        if (bubble) bubble.content = `[Not sent — Jarvis did not accept this message]\n\n${bubble.content}`;
      }
    }
    this.pendingDraft = null;
    this.pendingRequestId = null;
  }

  isSubmittedDraft() {
    return this.pendingDraft && JSON.stringify(this.state.draft) === JSON.stringify(this.pendingDraft);
  }

  acceptPendingDraft() {
    if (this.isSubmittedDraft()) this.state.draft = {text: '', attachment: null, context: null};
    this.pendingDraft = null;
  }

  onEvent(event, data) {
    if (event === 'connected') {
      this.state.connection = {...this.state.connection, status: 'connected', error: null};
      if (!this.state.conversationId && !this.pendingRequestId && ['cloud', 'local'].includes(data.mode)) {
        if (data.mode !== this.state.mode) this.clearImageHint();
        this.state.mode = data.mode;
      }
      this.recover();
      this.listConversations().catch(() => {});
    } else if (event === 'disconnect') {
      this.state.connection.status = 'disconnected';
      this.state.notice = 'Connection lost. Accepted work continues on Jarvis; reconnecting will recover its state.';
    } else if (event === 'connect_error') {
      const description = typeof data === 'string' ? data : data.message || data.data?.message || '';
      if (/auth|token|expired/i.test(description) || ['auth_required', 'authentication_required'].includes(data.data?.code)) return this.unauthorized();
      this.state.connection.status = 'error';
      this.state.connection.error = 'Unable to open the Jarvis connection. Check the server and network, then reconnect.';
    } else if (['auth:expired', 'auth:error', 'auth:required'].includes(event)) {
      return this.unauthorized();
    } else if (event === 'conversation:created') {
      if (!this.pendingRequestId || this.state.conversationId) return;
      this.state.conversationId = data.conversation_id;
      if (this.state.run) this.state.run.conversationId = data.conversation_id;
      this.updateSubmittedRequest(this.pendingRequestId, {conversationId: data.conversation_id});
    } else if (event === 'conversation:loaded') {
      const conversation = data.conversation;
      if (!conversation?.id || !this.pendingRequestId && !this.restoringConversation ||
          this.restoringConversation && this.restoringConversation !== conversation.id) return;
      const confirmed = !this.pendingRequestId || (conversation.messages || []).some(message =>
        message.data?._request_id === this.pendingRequestId) || conversation.run?.message_id === this.pendingRequestId;
      // Unrelated snapshots must not replace the request we are recovering.
      if (!confirmed) return;
      clearTimeout(this.recoveryTimer);
      this.restoringConversation = null;
      const changedConversation = this.state.conversationId !== conversation.id;
      this.state.conversationId = conversation.id;
      this.state.messages = savedMessages(conversation.messages);
      this.state.run = publicRun(conversation.run);
      for (const message of conversation.messages || []) {
        this.updateSubmittedRequest(message.data?._request_id, {conversationId: conversation.id});
      }
      this.updateSubmittedRequest(conversation.run?.message_id, {conversationId: conversation.id,
        status: conversation.run?.status});
      const changedMode = ['cloud', 'local'].includes(conversation.run?.mode) && this.state.mode !== conversation.run.mode;
      if (['cloud', 'local'].includes(conversation.run?.mode)) this.state.mode = conversation.run.mode;
      // A snapshot is authoritative only if it contains the unacknowledged request.
      if (confirmed) {
        this.pendingRequestId = null;
        this.acceptPendingDraft();
        this.state.connection.status = 'connected';
        this.state.notice = 'Conversation restored. Intermediate progress missed while disconnected may not be available.';
      } else {
        this.state.connection.status = 'error';
        this.state.notice = 'The previous request is not confirmed. Check recent conversations before sending it again.';
      }
      if (changedConversation || changedMode) this.clearImageHint();
      this.state.progress = [];
    } else if (event === 'chat:resume_missing') {
      if (!this.pendingRequestId || this.state.connection.status !== 'recovering') return;
      clearTimeout(this.recoveryTimer);
      this.state.connection.status = 'connected';
      this.state.notice = data.error || 'The previous request could not be confirmed. No work was resent. Check recent conversations.';
      this.state.run = null;
      this.updateSubmittedRequest(this.pendingRequestId, {status: 'unconfirmed'});
      this.restorePendingDraft();
    } else if (event === 'mode:changed') {
      clearTimeout(this.modeTimer);
      this.state.pendingMode = null;
      if (['cloud', 'local'].includes(data.mode)) {
        if (data.mode !== this.state.mode) this.clearImageHint();
        this.state.mode = data.mode;
      }
    } else if (event === 'mode:rejected') {
      clearTimeout(this.modeTimer);
      this.state.pendingMode = null;
      this.state.notice = data.error || 'Jarvis could not change mode while work is active.';
    } else if (event === 'chat:error' && this.restoringConversation && data.conversation_id === this.restoringConversation) {
      clearTimeout(this.recoveryTimer);
      this.restoringConversation = null;
      this.state.connection.status = 'connected';
      this.state.notice = data.error || 'Jarvis could not load this conversation.';
    } else {
      if (!this.eventBelongs(event, data)) return;
      if (event === 'chat:thinking') {
        this.pendingRequestId = null;
        this.acceptPendingDraft();
        clearTimeout(this.recoveryTimer);
        this.state.run = publicRun({...data, status: 'running'});
        this.state.conversationId = data.conversation_id || this.state.conversationId;
      } else if (event === 'chat:run') {
        this.state.run = publicRun(data);
        if (data.message_id === this.pendingRequestId) {
          this.pendingRequestId = null;
          this.acceptPendingDraft();
          clearTimeout(this.recoveryTimer);
        }
      } else if (event === 'chat:status') {
        if (this.isActive()) this.state.run.text = String(data.status || '').slice(0, 1000);
      } else if (event.startsWith('tool:')) {
        const id = `${data.message_id || ''}-${data.tool || 'tool'}-${data.call_index ?? ''}`;
        const item = {id, tool: String(data.tool || 'Tool').slice(0, 100), status: event.split(':')[1],
          text: String(data.status || data.message || data.error || '').slice(0, 1000)};
        const index = this.state.progress.findIndex(entry => entry.id === id);
        if (index === -1) this.state.progress.push(item); else this.state.progress[index] = item;
        this.state.progress = this.state.progress.slice(-20);
      } else if (event === 'chat:response') {
        const id = `assistant-${data.message_id}`;
        if (!this.state.messages.some(message => message.id === id || message.id === data.message_id && message.role === 'assistant')) {
          this.state.messages.push({id, role: 'assistant',
            content: String(data.text ?? data.response ?? data.raw_llm_response ?? data.speech ?? data.message ?? ''),
            createdAt: new Date().toISOString()});
        }
        this.pendingRequestId = null;
        this.acceptPendingDraft();
        clearTimeout(this.recoveryTimer);
        this.state.run = publicRun({...data, status: data.cancelled ? 'cancelled' : data.run_status || (data.ok === false ? 'failed' : 'completed')});
        this.listConversations().catch(() => {});
      } else if (['chat:error', 'chat:cancelled', 'chat:rejected'].includes(event)) {
        if (event === 'chat:rejected' || data.admitted === false) this.restorePendingDraft();
        if (event === 'chat:error' && this.restoringConversation) {
          clearTimeout(this.recoveryTimer);
          this.restoringConversation = null;
          this.state.connection.status = 'connected';
          this.state.run = null;
        }
        this.state.notice = data.error || (event === 'chat:cancelled' ? 'Request stopped.' : 'Jarvis could not complete the request.');
        this.pendingRequestId = null;
        this.pendingDraft = null;
        this.state.run = publicRun({...data, status: event === 'chat:cancelled' ? 'cancelled' : 'failed'});
        clearTimeout(this.recoveryTimer);
      } else if (event === 'cancel:ack' && this.state.run && data.status !== 'not_running') {
        this.state.run.status = 'stopping';
      }
      if (this.state.run?.messageId === data.message_id) {
        this.updateSubmittedRequest(data.message_id, {
          status: event === 'chat:rejected' || event === 'chat:error' && data.admitted === false ? 'rejected' : this.state.run.status,
          ...(data.conversation_id ? {conversationId: data.conversation_id} : {}),
        });
      }
    }
    this.state.messages = this.state.messages.slice(-100);
    this.changed();
  }

  async listConversations() {
    const transport = this.transport;
    if (!transport || !['connected', 'recovering'].includes(this.state.connection.status)) return;
    const result = await transport.listConversations();
    if (transport !== this.transport) return;
    this.state.conversations = (result.conversations || []).slice(0, 100).map(item => ({
      id: item.id, title: String(item.title || 'Untitled conversation'), updated_at: item.updated_at, pinned: item.pinned === true,
    }));
    this.changed();
  }

  async completionReader() {
    const serverUrl = normalizeServerUrl(this.state.settings.serverUrl, this.state.settings);
    const authScope = this.authScope;
    const token = this.token;
    const current = () => this.authScope === authScope && this.state.settings.serverUrl === serverUrl && this.intent;
    if (!current() || this.state.connection.authRequired && !token) throw new Error('Sign in before checking completed work.');
    if (!await this.permissions.contains({origins: [originPermission(serverUrl)]})) {
      throw new Error('Firefox permission for this server was removed.');
    }
    if (!current()) throw new Error('The Jarvis connection changed while checking completed work.');
    const transport = new JarvisTransport({serverUrl, token, fetchImpl: this.fetchImpl,
      onUnauthorized: () => { if (current()) this.unauthorized(); }});
    return async path => {
      if (!current()) throw new Error('The Jarvis connection changed while checking completed work.');
      const result = await transport.request(path);
      if (!current()) throw new Error('The Jarvis connection changed while checking completed work.');
      return result;
    };
  }

  async readConversation(conversationId) {
    if (!/^[A-Za-z0-9_-]{1,150}$/.test(conversationId || '')) throw new Error('Invalid conversation.');
    const read = await this.completionReader();
    return read(`/api/conversations/${encodeURIComponent(conversationId)}`);
  }

  async findSubmittedConversation(request) {
    if (!request?.requestId || !this.state.submittedRequests.some(item => item.requestId === request.requestId)) return null;
    const read = await this.completionReader();
    const result = await read('/api/conversations?limit=100&include_archived=false');
    const match = (result.conversations || []).find(item =>
      item.first_request_id === request.requestId || item.last_request_id === request.requestId);
    if (!match || !/^[A-Za-z0-9_-]{1,150}$/.test(match.id || '')) return null;
    return read(`/api/conversations/${encodeURIComponent(match.id)}`);
  }

  async loadConversation(conversationId) {
    this.requireIdle();
    if (!/^[A-Za-z0-9_-]{1,150}$/.test(conversationId || '')) throw new Error('Invalid conversation.');
    if (this.state.connection.status !== 'connected') throw new Error('Connect to Jarvis first.');
    this.restoringConversation = conversationId;
    this.state.connection.status = 'recovering';
    this.armRecoveryTimeout();
    this.transport.emit('conversation:load', {conversation_id: conversationId});
    this.changed();
  }

  async newConversation() {
    this.requireIdle();
    this.pendingRequestId = null;
    this.state.conversationId = null;
    this.state.messages = [];
    this.state.progress = [];
    this.state.run = null;
    this.state.notice = null;
    this.state.draft = {text: '', attachment: null, context: null};
    // Reconnect to leave the previous conversation's delivery room.
    this.close();
    this.state.connection.status = 'disconnected';
    await this.checkpoint();
    if (this.intent) await this.connect();
    this.publish();
  }

  async setMode(mode) {
    this.requireIdle();
    if (!['cloud', 'local'].includes(mode)) throw new Error('Choose cloud or local mode.');
    if (this.state.connection.status !== 'connected') throw new Error('Connect to Jarvis first.');
    this.state.pendingMode = mode;
    this.modeTimer = setTimeout(() => {
      this.state.notice = 'Mode change was not confirmed. Reconnect before sending.';
      this.close();
      this.state.connection.status = 'disconnected';
      this.changed();
    }, 15000);
    this.modeTimer.unref?.();
    try { this.transport.emit('mode:set', {mode}); }
    catch (error) { clearTimeout(this.modeTimer); this.state.pendingMode = null; throw error; }
    this.changed();
  }

  async setDraft(text, options = {}) {
    const context = this.state.draft.context;
    let draft = String(text || '').slice(0, 32000);
    if (context?.kind === 'image' && context.stageId && Object.hasOwn(options, 'imageStageId') && options.imageStageId !== context.stageId) {
      // A debounced edit from before staging must not erase the newly supplied
      // image. Edits that observed this stage may still remove its URL normally.
      draft = mergeImageStageText(draft, context);
    }
    this.state.draft.text = draft;
    if (this.state.draft.context?.kind === 'image' && !this.state.draft.text.includes(this.state.draft.context.url)) {
      this.clearImageHint();
    }
    await this.checkpoint();
    this.publish();
  }

  async stage({attachment = null, context = null, source = this.state.source}) {
    this.requireIdle();
    if (context?.kind === 'image') {
      let url;
      try { url = new URL(context.url); } catch {}
      if (!url || !['https:', 'http:'].includes(url.protocol) || url.username || url.password) {
        throw new Error('This image does not have a shareable HTTP or HTTPS URL. Use Capture page view instead.');
      }
      context = {kind: 'image', url: url.href, title: String(context.title || '').slice(0, 1000), text: '', stageId: crypto.randomUUID()};
      const text = mergeImageStageText(this.state.draft.text, context);
      this.state.draft.text = text;
    }
    this.state.source = source;
    this.state.draft.attachment = attachment;
    this.state.draft.context = context;
    this.state.notice = null;
    await this.checkpoint();
    this.publish();
  }

  async removeAttachment() { return this.stage({}); }

  clearImageHint() {
    if (this.state.draft.context?.kind === 'image') this.state.draft.context = null;
  }

  async send(text) {
    this.requireIdle();
    if (this.state.connection.status !== 'connected') throw new Error('Connect to Jarvis and finish recovery before sending.');
    const transport = this.transport;
    const attachment = this.state.draft.attachment;
    const context = this.state.draft.context;
    const original = String(text ?? this.state.draft.text).trim().slice(0, 32000);
    const toolHints = context?.kind === 'image' && original.includes(context.url) && !original.startsWith('/') ? ['analyze_image'] : [];
    let message = original || (attachment ? DEFAULT_PROMPT : context ? 'Explain this selected browser content.' : '');
    if (!message) throw new Error('Enter a message or capture a screenshot.');
    if (attachment?.source) {
      message += `\n\nScreenshot source: ${attachment.source.title}\n${attachment.source.url}\nCaptured: ${attachment.capturedAt}`;
    }
    if (context && context.kind !== 'image') {
      message += `\n\nBrowser content supplied for reference:\nTitle: ${context.title || ''}\nURL: ${context.url || ''}\n${context.text || ''}`;
    }
    let image;
    this.uploading = true;
    this.state.draft.text = original;
    this.state.connection.status = 'recovering';
    this.state.notice = attachment ? 'Uploading screenshot…' : null;
    this.publish();
    try {
      await this.checkpoint();
      if (attachment) image = {action: 'analyze', images: [await transport.upload(attachment, this.state.mode)]};
      if (transport !== this.transport || !transport.socket?.connected) throw new Error('Disconnected before sending. The draft is retained; reconnect first.');
      const requestId = this.uuid();
      this.pendingRequestId = requestId;
      this.pendingDraft = {...structuredClone(this.state.draft), text: original};
      this.state.run = {requestId, messageId: requestId, conversationId: this.state.conversationId, status: 'sending'};
      this.state.submittedRequests.push({requestId, conversationId: this.state.conversationId,
        mode: this.state.mode, startedAt: new Date().toISOString(), status: 'sending'});
      this.state.submittedRequests = submittedRequests(this.state.submittedRequests);
      this.state.messages.push({id: `user-${requestId}`, role: 'user', content: message,
        createdAt: new Date().toISOString(), attachments: attachment ? [{previewUrl: attachment.previewUrl}] : []});
      this.state.progress = [];
      this.state.notice = null;
      this.state.connection.status = 'connected';
      // Crash before/after this write is safe: recovery only looks up this ID.
      // Never persist a payload that an automatic retry could execute again.
      await this.checkpoint();
      this.state.draft = {text: '', attachment: null, context: null};
      transport.emit('chat:send', {message, mode: this.state.mode,
        conversation_id: this.state.conversationId, request_id: requestId, ...(image ? {image} : {}),
        ...(toolHints.length ? {tool_hints: toolHints} : {})});
      if (this.pendingRequestId) this.armRecoveryTimeout();
      this.changed();
    } catch (error) {
      if (!this.pendingRequestId && this.transport === transport && transport.socket?.connected) this.state.connection.status = 'connected';
      if (this.pendingRequestId) {
        if (this.pendingDraft) this.state.draft = structuredClone(this.pendingDraft);
        this.state.run = {...this.state.run, status: 'recovering'};
        this.state.connection.status = 'error';
        this.state.notice = 'Delivery is not confirmed. Reconnect to check the request before sending again.';
        this.close();
      }
      this.publish();
      throw error;
    } finally { this.uploading = false; }
  }

  async cancel() {
    const run = this.state.run;
    if (!run || !this.isActive()) return;
    if (this.state.connection.status !== 'connected' || !run.conversationId) {
      throw new Error('Reconnect and recover the request before stopping it.');
    }
    this.transport.emit('chat:cancel', {conversation_id: run.conversationId, message_id: run.messageId});
    this.state.run.status = 'stopping';
    this.changed();
  }
}
