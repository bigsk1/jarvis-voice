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
    this.browserSetupTimer = null;
    this.browserSetupPending = false;
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
      const setup = status.tool_details?.browser_use?.browser_use?.setup;
      if (setup?.state === 'running') {
        this.browserSetupPending = true;
        if (!this.browserSetupTimer) this.browserSetupTimer = setTimeout(() => {
          this.browserSetupTimer = null; void this.refresh();
        }, 1500);
      } else {
        if (this.browserSetupTimer) clearTimeout(this.browserSetupTimer);
        this.browserSetupTimer = null;
        if (this.browserSetupPending && setup) {
          this.browserSetupPending = false;
          if (setup.state === 'ready') Utils.toast('Browser Use is configured and enabled.', 'success');
          else if (setup.state === 'failed') Utils.toast(setup.message || 'Browser Use setup failed.', 'warning');
        }
      }
      this.view?.availability(status);
      this.updateConvertHint();
      if (!this.control) return;
      this.control.hidden = false;
      this.enabledInput.checked = this.enabled;
      this.enabledInput.disabled = this.saving === true || Boolean(status.coordinator_unavailable_reason);
      const saved = new Set(status.settings.background_tools || []);
      const availableSaved = [...saved].some(name => status.tools.includes(name)
        && status.tool_details?.[name]?.browser_use?.deployment_supported !== false);
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
        const browser = details?.browser_use;
        const privateCallback = details?.private_callback;
        if (name === 'browser_use' && browser && (!browser.operational || browser.deployment_supported === false)
            && !input.checked) input.disabled = true;
        if (privateCallback && (!privateCallback.policy_ready || !privateCallback.source_ready || !privateCallback.service_ready) && !input.checked) input.disabled = true;
        description.textContent = name === 'browser_use' && browser ? (browser.deployment_supported === false
          ? 'Native install only. Browser Use is unavailable when Jarvis runs in Docker.'
          : browser.setup?.state === 'running'
          ? browser.setup.message || 'Setting up Browser Use…'
          : browser.setup?.state === 'failed' ? browser.setup.message
          : !browser.configured
          ? 'Set up once here; Jarvis will configure callbacks and own the helper service.'
          : browser.ready ? 'Ready for Web chat → background task → callback.'
          : browser.operational ? 'Setup is ready. Enable the background switch and Browser Use to make it available in Web chat.'
          : !browser.service_ready ? 'Configured, but the Browser Use helper is stopped.'
          : !browser.worker_ready ? 'Helper is running; the task worker is loading its callback adapter.'
          : 'Setup needs attention. Use Finish setup to repair and verify it.')
          : privateCallback ? (!available
          ? 'Unavailable in this mode or blocked in Web. Saved preference retained if selected.'
          : !privateCallback.policy_ready
          ? 'Private tool policy changed or this mode blocks it. Review its binding and tool settings.'
          : !privateCallback.source_ready
          ? 'Callback source is unavailable. Check Settings → Integrations and test the receiver.'
          : !privateCallback.service_ready ? 'The private task service is not responding.'
          : !details.worker_ready ? 'The task worker must be restarted to load this private callback tool.'
          : 'Ready for Web chat → private task service → late answer.')
          : name === 'browser_use_cloud' && !available ? (input.checked
          ? 'Unavailable in this mode: check the Browser Use Cloud API key and Web/profile blocks. Saved preference retained.'
          : 'Requires BROWSER_USE_API_KEY in this mode and an allowed Web tool profile.')
          : !available ? (input.checked
          ? 'Unavailable in this mode or blocked in Web. Saved preference retained; uncheck to remove.'
          : 'Unavailable in this mode or blocked in Web.')
          : details?.worker_ready === false ? 'A compatible worker must be started or restarted before this tool can queue.'
          : name === 'browser_use_cloud' ? 'Hosted browser research. Watch it live from the task card; the run has a $3 cap, and Jarvis checks browser shutdown at completion.'
          : details?.remote_work ? 'Runs with a remote provider. Interrupted jobs require review; stopping Jarvis does not cancel provider work.'
          : 'Use background execution when enabled above.';
        text.append(description);
        label.append(input, text);
        if (name === 'browser_use' && browser && browser.deployment_supported !== false) label.append(this.browserActions(browser));
        this.choices.append(label);
      }
      this.note.textContent = setup?.state === 'running' ? 'Browser Use setup is running. You can keep chatting while the pinned image downloads.'
        : status.coordinator_unavailable_reason
        || (!this.choices.children.length ? 'No supported background tools are installed.'
        : !status.worker_ready ? 'Worker offline. Preferences are saved, but enabled tools cannot queue until it starts. Open Manage tasks for setup.'
        : this.enabled && saved.size && !availableSaved ? 'Selected background tools are unavailable in this deployment.'
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

  browserActions(browser) {
    const actions = document.createElement('div');
    actions.className = 'background-tool-actions';
    const button = (text, action) => {
      const control = document.createElement('button');
      control.type = 'button'; control.className = 'btn-secondary'; control.textContent = text;
      control.addEventListener('click', async event => {
        event.preventDefault(); event.stopPropagation(); control.disabled = true;
        const original = control.textContent;
        control.textContent = action === 'setup' ? 'Setting up…' : 'Working…';
        try {
          const response = await Utils.auth.fetch('/api/background-tasks/tools/browser_use/actions', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({action})
          });
          const value = await response.json();
          if (!response.ok) throw new Error(value.error || 'Browser Use setup failed');
          if (action === 'setup' && response.status === 202) this.browserSetupPending = true;
          Utils.toast(action === 'setup' && response.status === 202 ? 'Browser Use setup started. Progress will appear here.'
            : action === 'setup' ? 'Browser Use is configured and enabled.'
            : action === 'test' ? 'Browser Use callback verified.'
            : `Browser Use service ${action} complete.`, 'success');
        } catch (error) { Utils.toast(error.message, 'warning'); }
        control.textContent = original;
        await this.refresh();
      });
      return control;
    };
    if (browser.setup?.state === 'running') {
      const progress = button('Setting up…', 'setup'); progress.disabled = true; actions.append(progress);
    }
    else if (!browser.configured) actions.append(button(browser.setup?.state === 'failed' ? 'Retry setup' : 'Set up and enable', 'setup'));
    else if (!browser.operational) {
      actions.append(button('Finish setup', 'setup'));
      if (!browser.service_ready) actions.append(button('Start service', 'start'));
    } else {
      actions.append(button('Test connection', 'test'));
      if (browser.managed_by_tmux) {
        actions.append(button('Restart service', 'restart'), button('Stop service', 'stop'));
      }
    }
    return actions;
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
      title.textContent = `${job.tool === 'browser_use_cloud' ? 'Browser Use Cloud' : job.tool} · ${state}${delivery}`;
      const live = job.tool === 'browser_use_cloud' && !['succeeded', 'failed', 'cancelled', 'expired'].includes(job.state)
        ? job.progress?.live_view_url : null;
      let liveUrl = null;
      try {
        const parsed = new URL(live);
        if (parsed.protocol === 'https:' && parsed.hostname === 'live.browser-use.com'
            && !parsed.username && !parsed.password && (!parsed.port || parsed.port === '443')) liveUrl = parsed.href;
      } catch (_) { /* No verified live viewer yet. */ }
      if (liveUrl) {
        const watch = document.createElement('a');
        watch.className = 'background-job-live';
        watch.textContent = 'Watch browser live ↗';
        watch.href = liveUrl;
        watch.target = '_blank'; watch.rel = 'noopener noreferrer';
        watch.addEventListener('click', event => event.stopPropagation());
        title.append(watch);
      }
      const body = document.createElement('pre');
      body.textContent = (job.delivery_error ? `${job.delivery_error}\n\n` : '') + (job.archived_at ? 'Result payload archived. Saved conversation answers and artifacts remain available.'
        : job.result ? JSON.stringify(job.result, null, 2).slice(0, 12000)
        : job.attention_reason || job.progress?.phase || 'Results will return to this conversation.');
      const children = [title, body];
      const researchRef = ['browser_use', 'browser_use_cloud'].includes(job.tool)
        ? job.result?.data?.browser_research?.stash_ref : null;
      const researchUrl = window.mediaResultRenderer?.stashUrl(researchRef)?.replace('/api/stash/', '/stash/view/');
      if (researchUrl) {
        const link = document.createElement('a');
        link.className = 'btn-secondary background-job-research';
        link.textContent = 'Open saved research';
        link.href = researchUrl + (['cloud', 'local'].includes(job.mode) ? `?mode=${job.mode}` : '');
        link.target = '_blank'; link.rel = 'noopener noreferrer';
        children.push(link);
      }
      if (job.can_cancel) {
        const cancel = document.createElement('button');
        cancel.type = 'button'; cancel.className = 'btn-secondary background-job-cancel';
        cancel.textContent = 'Request cancellation';
        cancel.addEventListener('click', async event => {
          event.preventDefault(); event.stopPropagation(); cancel.disabled = true;
          try {
            const response = await Utils.auth.fetch(`/api/background-jobs/${encodeURIComponent(job.job_id)}/actions`, {
              method: 'POST', headers: {'Content-Type': 'application/json'},
              body: JSON.stringify({action: 'cancel', revision: job.revision})
            });
            const value = await response.json();
            if (!response.ok) throw new Error(value.error || 'Cancellation could not be requested');
            Utils.toast('Cancellation requested. Jarvis will confirm when this browser job has stopped.', 'info');
          } catch (error) {
            Utils.toast(error.message, 'warning'); cancel.disabled = false;
          }
        });
        children.push(cancel);
      }
      card.replaceChildren(...children);
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
