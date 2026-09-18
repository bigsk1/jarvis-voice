/** Background jobs never activate foreground pendingTools or settle a live turn. */
class BackgroundTasks {
  constructor(app) {
    this.app = app;
    this.socket = app.socket;
    this.chat = app.chat;
    this.control = document.getElementById('backgroundSettings');
    this.enabledInput = document.getElementById('backgroundEnabled');
    this.choices = document.getElementById('backgroundChoices');
    this.note = document.getElementById('backgroundNote');
    this.generations = new Map();
    this.revisions = new Map();
    this.jobs = new Map();
    this.unread = new Set();
    this.enabled = false;
    this.refreshId = 0;
    this.view = window.TaskManager ? new window.TaskManager(this) : null;
    this.socket.on('taskOverview', data => this.view?.counts(data));
    this.socket.on('sessionReady', () => { void this.refresh(); this.subscribe(); });
    this.socket.on('modeChanged', () => { void this.refresh(); });
    this.socket.on('conversationCreated', data => {
      this.generations.set(data.conversation_id, 0);
      this.subscribe(data.conversation_id);
    });
    this.socket.on('conversationLoaded', data => {
      const generation = data.conversation.generation || 0;
      if ((this.generations.get(data.conversation.id) ?? -1) > generation) return;
      this.generations.set(data.conversation.id, generation);
      this.unread.delete(data.conversation.id);
      this.subscribe(data.conversation.id);
    });
    this.socket.on('tasksSnapshot', data => {
      if ((this.generations.get(data.conversation_id) ?? -1) > data.generation) return;
      this.generations.set(data.conversation_id, data.generation);
      for (const job of data.jobs || []) this.update(job);
    });
    this.socket.on('taskUpdated', data => this.update(data));
    this.socket.on('continuation', data => this.continuation(data));
    this.enabledInput?.addEventListener('change', () => { void this.savePreferences(); });
  }

  subscribe(id = this.socket.conversationId) {
    this.socket.emit('tasks:watch', {});
    if (id) this.socket.emit('tasks:subscribe', { conversation_id: id });
  }

  async refresh() {
    const requestId = ++this.refreshId;
    try {
      const response = await Utils.auth.fetch(`/api/background-tasks?mode=${encodeURIComponent(this.socket.mode)}`);
      if (requestId !== this.refreshId) return;
      if (!response.ok) throw new Error('Sign in with Web operator access to manage background tasks.');
      const status = await response.json();
      if (requestId !== this.refreshId) return;
      this.enabled = status.settings.background_enabled;
      this.status = status;
      this.view?.availability(status);
      this.updateConvertHint();
      if (!this.control) return;
      this.control.hidden = false;
      this.enabledInput.checked = this.enabled;
      this.enabledInput.disabled = this.saving === true || Boolean(status.coordinator_unavailable_reason);
      const saved = new Set(status.settings.background_tools || []);
      this.choices.replaceChildren();
      for (const name of new Set([...(status.configured_tools || status.tools), ...saved])) {
        const label = document.createElement('label');
        label.className = 'background-tool-option';
        const input = document.createElement('input');
        input.type = 'checkbox'; input.value = name; input.checked = saved.has(name);
        const available = status.tools.includes(name);
        // Saved choices span modes. Allow clearing an unavailable saved choice,
        // but never offer a new selection that this mode cannot execute.
        input.disabled = this.saving === true || Boolean(status.coordinator_unavailable_reason)
          || (!available && !input.checked);
        input.addEventListener('change', () => { void this.savePreferences(); });
        const text = document.createElement('span');
        text.textContent = name.replaceAll('_', ' ').replace(/^./, ch => ch.toUpperCase());
        const description = document.createElement('small');
        const details = status.tool_details?.[name];
        description.textContent = !available ? (input.checked
          ? 'Unavailable in this mode or blocked in Web. Saved preference retained; uncheck to remove.'
          : 'Unavailable in this mode or blocked in Web.')
          : details?.worker_ready === false ? 'A compatible worker must be started or restarted before this tool can queue.'
          : details?.remote_work ? 'Runs with a remote provider. Interrupted jobs require review; stopping Jarvis does not cancel provider work.'
          : 'Use background execution when enabled above.';
        text.append(description);
        label.append(input, text);
        this.choices.append(label);
      }
      this.note.textContent = status.coordinator_unavailable_reason
        || (!this.choices.children.length ? 'No supported background tools are installed.'
        : !status.worker_ready ? 'Worker offline. Preferences are saved, but enabled tools cannot queue until it starts. Open Manage tasks for setup.'
        : this.enabled && saved.size ? 'Ready. Enabled tools run in the background from chat and tool dialogs.'
        : this.enabled ? 'Choose a tool below to use background execution.' : 'Off. Tools run in the current chat turn.');
    } catch (error) {
      this.status = null;
      if (this.note) this.note.textContent = error.message;
      if (this.enabledInput) this.enabledInput.disabled = true;
      this.choices?.querySelectorAll('input').forEach(input => { input.disabled = true; });
      this.updateConvertHint();
    }
  }

  async savePreferences() {
    if (this.saving) return;
    this.saving = true;
    ++this.refreshId;
    const selected = Array.from(this.choices.querySelectorAll('input:checked')).map(input => input.value);
    this.enabledInput.disabled = true;
    this.choices.querySelectorAll('input').forEach(input => { input.disabled = true; });
    try {
      const response = await Utils.auth.fetch('/api/background-tasks', {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ background_enabled: this.enabledInput.checked, background_tools: selected })
      });
      if (!response.ok) throw new Error((await response.json()).error || 'Setting could not be saved');
    } catch (error) { Utils.toast(error.message, 'warning'); }
    this.saving = false;
    await this.refresh();
  }

  updateConvertHint() {
    const note = document.getElementById('convertExecutionNote');
    if (!note) return;
    const status = this.status;
    const enabled = status?.settings.background_enabled && status.settings.background_tools?.includes('convert_file')
      && status.tools.includes('convert_file');
    note.textContent = !status ? 'Execution mode follows Settings → Tools.'
      : !enabled ? 'Runs in this chat. Background execution can be enabled in Settings → Tools.'
      : !(status.tool_details?.convert_file?.worker_ready ?? status.worker_ready) || !status.coordinator_ready ? 'Background execution is enabled, but the worker is unavailable. Open Manage tasks in Settings → Tools for setup.'
      : 'Runs in the background. You can keep chatting; the converted file will return here.';
  }

  async dispose(conversationId, action) {
    const response = await Utils.auth.fetch(`/api/conversations/${encodeURIComponent(conversationId)}`);
    if (!response.ok) throw new Error('Reload the conversation before disposing its background tasks.');
    const { conversation } = await response.json();
    if (!confirm(`${action === 'clear' ? 'Clear' : 'Delete'} this conversation and discard its pending background replies? Running operations may continue.`)) return false;
    const disposed = await Utils.auth.fetch(`/api/background-tasks/conversations/${encodeURIComponent(conversationId)}/dispose`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action, generation: conversation.generation })
    });
    if (!disposed.ok) throw new Error((await disposed.json()).error || 'Background disposition failed');
    this.generations.set(conversationId, action === 'clear' ? conversation.generation + 1 : Infinity);
    return true;
  }

  belongs(data) {
    const displayed = this.app._displayedConversationId || this.socket.conversationId;
    return data.conversation_id === displayed && this.generations.get(displayed) === data.generation;
  }

  renderCards(message, jobs) {
    for (const incoming of Object.values(jobs || {})) {
      const cached = this.jobs.get(incoming.job_id);
      const job = cached && cached.revision > incoming.revision ? cached : incoming;
      let card = Array.from(message.querySelectorAll('[data-background-job]')).find(el => el.dataset.backgroundJob === job.job_id);
      if (!card) {
        card = document.createElement('details');
        card.className = 'tool-card background-job';
        card.dataset.backgroundJob = job.job_id;
        message.prepend(card);
      }
      const wasOpen = card.open;
      const title = document.createElement('summary');
      title.className = 'tool-card-header';
      const state = job.state === 'succeeded' ? 'Completed' : String(job.state || 'queued').replaceAll('_', ' ');
      const delivery = job.delivery_error ? ' · reply delayed'
        : job.delivery_state && !['delivered', 'suppressed'].includes(job.delivery_state) ? ' · reply pending' : '';
      title.textContent = `${job.tool} · ${state}${delivery}`;
      const body = document.createElement('pre');
      body.textContent = (job.delivery_error ? `${job.delivery_error}\n\n` : '') + (job.archived_at ? 'Result payload archived. Saved conversation answers and artifacts remain available.'
        : job.result ? JSON.stringify(job.result, null, 2).slice(0, 12000)
        : job.attention_reason || job.progress?.phase || 'Results will return to this conversation.');
      card.replaceChildren(title, body);
      card.open = wasOpen;
    }
  }

  update(data) {
    if (data.schema_version !== 1 || (this.generations.get(data.conversation_id) ?? -1) > data.generation) return;
    if (!this.generations.has(data.conversation_id)) this.generations.set(data.conversation_id, data.generation);
    const previous = this.revisions.get(data.job_id) || 0;
    if (data.revision <= previous) return;
    this.revisions.set(data.job_id, data.revision);
    this.jobs.set(data.job_id, data);
    this.view?.changed();
    if (this.jobs.size > 500) {
      const oldest = this.jobs.keys().next().value;
      this.jobs.delete(oldest); this.revisions.delete(oldest);
    }
    if (!this.belongs(data)) {
      if (data.unread) this.unread.add(data.conversation_id);
      return;
    }
    const message = Array.from(this.chat.messagesContainer.querySelectorAll('.message.assistant'))
      .find(el => el.dataset.messageId === data.source_message_id);
    if (message) this.renderCards(message, { [data.job_id]: data });
  }

  continuation(data) {
    if (data.schema_version !== 1 || !data.message || !data.continuation_id) return;
    if (!this.belongs(data)) {
      if (this.generations.get(data.conversation_id) === data.generation) {
        this.unread.add(data.conversation_id);
        if (this.note) this.note.textContent = 'A background result arrived in another conversation.';
      }
      return;
    }
    if (this.chat._renderedMessageIds?.has(`assistant:${data.continuation_id}`)) return;
    this.chat.addAssistantMessage(data.message.content, [], {
      ...(data.message.data || {}), message_id: data.continuation_id, conversation_id: data.conversation_id,
      _background_mode: data.message.data?._background_mode || this.jobs.get(data.job_id)?.mode
    }, { late: true, allowReaction: false });
    void this.app._loadConversationHistory();
  }
}
window.BackgroundTasks = BackgroundTasks;
