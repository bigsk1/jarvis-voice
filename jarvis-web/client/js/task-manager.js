/** Operator task management. Every result, label, and error is rendered as text. */
window.TaskManager = class TaskManager {
  constructor(background) {
    this.background = background;
    this.offset = 0; this.serial = 0;
    this.launch = document.getElementById('backgroundTasksButton');
    this.launch?.addEventListener('click', () => this.open());
    document.getElementById('backgroundManage')?.addEventListener('click', () => this.open());
    this.dialog = this.node('dialog', '', 'task-manager');
    this.dialog.setAttribute('aria-label', 'Background tasks');
    const heading = this.node('header', '', 'task-heading');
    const title = this.node('div');
    title.append(this.node('h2', 'Background tasks'), this.node('p', 'Your work keeps going. Results return to the conversation.'));
    const close = this.button('✕', () => this.dialog.close());
    close.className = 'icon-btn'; close.setAttribute('aria-label', 'Close background tasks');
    heading.append(title, close);
    const body = this.node('div', '', 'task-body');
    this.stats = this.node('div', '', 'task-stats');
    this.statValues = {};
    for (const [key, title] of [['outstanding','In progress'],['running','Running'],['reserved','Needs attention']]) {
      const card = this.node('div', '', 'task-stat');
      this.statValues[key] = this.node('strong', '0');
      card.append(this.statValues[key], this.node('span', title)); this.stats.append(card);
    }
    this.summary = this.node('p', '', 'task-status'); this.summary.setAttribute('role', 'status');
    this.error = this.node('p', '', 'task-error'); this.error.setAttribute('role', 'alert');
    this.setup = this.node('div', '', 'task-setup');
    const setupText = this.node('div');
    setupText.append(this.node('strong', 'Connect a background worker'),
      this.node('p', 'Your preferences are saved. A worker must be running before enabled tools can queue. See Background tasks in Docs for setup.'));
    this.setup.append(setupText, this.button('Open Docs', () => {
      this.dialog.close(); document.getElementById('settingsModal')?.classList.remove('active');
      document.getElementById('openDocsViewerBtn')?.click();
    }));
    const settings = this.node('details', '', 'task-advanced'); settings.append(this.node('summary', 'Advanced limits and retention'));
    const limits = this.node('div', '', 'task-limits');
    this.limits = {};
    for (const [key, title, max] of [['max_running', 'Running jobs', 32], ['max_per_adapter', 'Running per adapter', 32],
      ['max_outstanding', 'Outstanding per conversation', 100], ['max_queued', 'Queued jobs', 10000], ['result_retention_days', 'Result retention (days)', 3650]]) {
      const input = this.node('input'); input.type = 'number'; input.min = '1'; input.max = String(max);
      this.limits[key] = input; limits.append(this.label(title, input));
    }
    settings.append(limits);
    this.retentionButton = this.button('Preview retention', () => this.previewRetention());
    this.retentionPreview = this.node('p', '', 'task-retention-preview');
    this.retentionPreview.setAttribute('role', 'status'); this.retentionPreview.hidden = true;
    settings.append(this.button('Save settings', () => this.saveSettings()), this.retentionButton,
      this.node('p', 'Preview checks the saved retention period. Save settings first to preview changes. Cleanup removes old task result details; saved messages and generated files are kept.'),
      this.retentionPreview);
    const filters = this.node('form', '', 'task-filters');
    this.conversation = this.node('select'); this.tool = this.node('select'); this.state = this.node('select');
    this.conversation.append(this.option('', 'All conversations'));
    this.tool.append(this.option('', 'All tools'));
    this.state.append(this.option('', 'All states'));
    for (const state of ['queued','starting','running','cancel_requested','needs_attention','succeeded','failed','cancelled','expired']) {
      this.state.append(this.option(state, state.replaceAll('_', ' ')));
    }
    filters.append(this.label('Conversation', this.conversation), this.label('Tool', this.tool), this.label('Status', this.state));
    const filter = this.button('Filter', () => {}); filter.type = 'submit'; filters.append(filter);
    filters.addEventListener('submit', event => { event.preventDefault(); this.offset = 0; void this.refresh(); });
    this.rows = this.node('div', '', 'task-rows');
    const filterPanel = this.node('details', '', 'task-filter-panel');
    filterPanel.append(this.node('summary', 'Filter tasks'), filters);
    this.previous = this.button('Previous', () => { this.offset = Math.max(0, this.offset - 25); void this.refresh(); });
    this.next = this.button('Next', () => { this.offset = this.nextOffset; void this.refresh(); });
    this.page = this.node('span');
    const paging = this.node('footer', '', 'task-paging');
    const navigation = this.node('div', '', 'task-actions'); navigation.append(this.previous, this.page, this.next);
    paging.append(navigation, this.button('Refresh', () => this.refresh()));
    this.details = this.node('section', '', 'task-inspector');
    const preferences = this.button('Background settings', () => {
      this.dialog.close(); document.getElementById('settingsBtn')?.click();
      document.querySelector('[data-settings-tab="tools"]')?.click();
    });
    const statusBar = this.node('div', '', 'task-status-bar'); statusBar.append(this.summary, preferences);
    body.append(this.stats, statusBar, this.error, this.setup, filterPanel, this.rows, this.details, settings);
    this.dialog.append(heading, body, paging);
    document.body.append(this.dialog);
    this.dialog.addEventListener('close', () => { clearTimeout(this.timer); ++this.serial; });
  }
  node(tag, text = '', className = '') {
    const node = document.createElement(tag); node.textContent = text; node.className = className; return node;
  }
  button(title, action) {
    const button = this.node('button', title, 'btn-secondary'); button.type = 'button';
    button.addEventListener('click', () => { Promise.resolve().then(action).catch(error => { this.error.textContent = error.message; }); });
    return button;
  }
  label(title, control) { const label = this.node('label', title); label.append(control); return label; }
  option(value, text) { const option = this.node('option', text); option.value = value; return option; }
  async request(path, body, method = 'POST') {
    const response = await Utils.auth.fetch(path, body === undefined ? {} : {
      method, headers: {'Content-Type':'application/json'}, body: JSON.stringify(body)
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Task request failed');
    return data;
  }
  counts(counts = {}) {
    if (this.launch) {
      this.launch.textContent = `🧵${counts.outstanding ? ' ' + counts.outstanding : ''}${counts.unread ? ' •' : ''}`;
      this.launch.title = `Background tasks: ${counts.outstanding || 0} outstanding, ${counts.unread || 0} unread`;
      this.launch.setAttribute('aria-label', this.launch.title);
    }
  }
  availability(status) { if (this.launch) this.launch.hidden = false; this.counts(status.counts); }
  async open() { if (!this.dialog.open) this.dialog.showModal(); await this.refresh(true); }
  changed() {
    if (!this.dialog.open) return;
    clearTimeout(this.timer); this.timer = setTimeout(() => { void this.refresh(); }, 200);
  }
  async refresh(settings = false) {
    const serial = ++this.serial;
    try {
      const query = new URLSearchParams({offset:String(this.offset),limit:'25'});
      if (this.conversation.value.trim()) query.set('conversation_id', this.conversation.value.trim());
      if (this.tool.value.trim()) query.set('tool', this.tool.value.trim());
      if (this.state.value) query.set('state', this.state.value);
      const [page, status] = await Promise.all([this.request('/api/background-jobs?' + query),
        this.request('/api/background-tasks?mode=' + encodeURIComponent(this.background.socket.mode))]);
      if (serial !== this.serial || !this.dialog.open) return;
      this.error.textContent = ''; this.availability(status);
      for (const [key, value] of Object.entries(this.statValues)) value.textContent = String(page.counts[key] || 0);
      this.summary.textContent = status.coordinator_unavailable_reason || (!status.worker_ready ? 'Worker offline'
        : !status.settings.background_enabled ? 'Background execution is off' : 'Ready for background work');
      this.summary.dataset.ready = String(status.worker_ready);
      this.setup.hidden = status.worker_ready;
      if (settings) {
        for (const [key, input] of Object.entries(this.limits)) input.value = status.settings[key];
        const conversation = this.conversation.value, tool = this.tool.value;
        this.conversation.replaceChildren(this.option('', 'All conversations'));
        const current = this.background.socket.conversationId;
        if (current) this.conversation.append(this.option(current, 'Current conversation'));
        if (conversation && conversation !== current) this.conversation.append(this.option(conversation, 'Previously selected conversation'));
        this.conversation.value = conversation;
        this.tool.replaceChildren(this.option('', 'All tools'));
        for (const name of new Set([...(status.configured_tools || status.tools), ...page.jobs.map(job => job.tool), ...(tool ? [tool] : [])])) {
          this.tool.append(this.option(name, name.replaceAll('_', ' ')));
        }
        this.tool.value = tool;
      }
      this.rows.replaceChildren();
      if (!page.jobs.length) {
        const empty = this.node('div', '', 'task-empty');
        const filtered = this.conversation.value || this.tool.value || this.state.value;
        empty.append(this.node('span', '◷', 'task-empty-icon'), this.node('h3', filtered ? 'No matching tasks' : 'No background tasks yet'),
          this.node('p', filtered ? 'Try a different filter to find your tasks.' : 'Enable a supported tool in Settings → Tools, then use it from chat or its dialog. Your tasks and results will appear here.'));
        this.rows.append(empty);
      }
      for (const job of page.jobs) {
        const row = this.node('article', '', 'task-row');
        const rowHeading = this.node('div', '', 'task-row-heading');
        const badge = this.node('span', job.state.replaceAll('_', ' '), 'task-state');
        badge.dataset.state = job.state;
        const badges = this.node('div', '', 'task-badges');
        if (job.unread) {
          const unread = this.node('span', 'Unread', 'task-unread');
          unread.title = 'Task details have not been viewed. Open Details to mark as read.';
          badges.append(unread);
        }
        badges.append(badge);
        rowHeading.append(this.node('strong', job.tool.replaceAll('_', ' ')), badges);
        row.append(rowHeading);
        row.append(this.node('p', `${job.mode} · ${new Date(job.created_at * 1000).toLocaleString()} · Follow-up: ${job.delivery_state || 'waiting for result'}`));
        if (job.archived_at) row.append(this.node('p', 'Result payload archived. Saved conversation messages and artifacts remain available.'));
        if (job.attention_reason || job.delivery_error) row.append(this.node('p', job.attention_reason || job.delivery_error));
        if (job.remote_work && ['starting','running','needs_attention'].includes(job.state)) {
          row.append(this.node('p', 'Provider work may continue if Jarvis stops. Remote cancellation is not available here.'));
        }
        const actions = this.node('div', '', 'task-actions');
        actions.append(this.button('Details', () => this.inspect(job.job_id)),
          this.button('Open conversation', () => {
            this.dialog.close(); document.getElementById('settingsModal')?.classList.remove('active');
            this.background.app.loadConversation(job.conversation_id);
          }));
        for (const [allowed, action, title] of [[job.can_cancel,'cancel','Request cancellation'],
          [job.can_retry_delivery,'retry_delivery','Retry follow-up'],[job.can_suppress_delivery,'suppress_delivery','Suppress follow-up']]) {
          if (allowed) actions.append(this.button(title, () => this.act(job, action)));
        }
        row.append(actions); this.rows.append(row);
      }
      this.nextOffset = page.next_offset;
      this.previous.disabled = this.offset === 0; this.next.disabled = page.next_offset === null;
      this.previous.hidden = this.next.hidden = page.total <= 25 && this.offset === 0;
      this.page.textContent = page.total ? `${page.jobs.length ? this.offset + 1 : 0}–${this.offset + page.jobs.length} of ${page.total}` : '0 tasks';
    } catch (error) { if (serial === this.serial) this.error.textContent = error.message; }
  }
  async saveSettings() {
    const changes = {};
    for (const [key, input] of Object.entries(this.limits)) changes[key] = Number(input.value);
    await this.request('/api/background-tasks', changes, 'PATCH');
    this.retentionPreview.hidden = true; this.retentionPreview.textContent = '';
    await this.background.refresh(); await this.refresh(true);
  }
  async previewRetention() {
    this.retentionButton.disabled = true;
    this.retentionPreview.hidden = false; this.retentionPreview.dataset.error = 'false';
    this.retentionPreview.textContent = 'Checking the saved retention policy…';
    try {
      const preview = await this.request('/api/background-tasks/retention');
      const count = preview.eligible_in_next_batch;
      this.retentionPreview.textContent = (count
        ? `${count} finished task result${count === 1 ? '' : 's'} eligible for cleanup in the next batch (up to ${preview.batch_limit}).`
        : 'No finished task results are currently eligible for cleanup.') + ' Preview only — nothing was changed.';
    } catch (error) {
      this.retentionPreview.dataset.error = 'true';
      this.retentionPreview.textContent = `Could not preview retention: ${error.message}`;
    } finally {
      this.retentionButton.disabled = false;
      this.retentionPreview.scrollIntoView({block: 'nearest'});
    }
  }
  async act(job, action, extra = {}) {
    await this.request(`/api/background-jobs/${encodeURIComponent(job.job_id || job.id)}/actions`, {action, revision:job.revision, ...extra});
    await this.refresh();
  }
  async inspect(id) {
    const {job} = await this.request(`/api/background-jobs/${encodeURIComponent(id)}/actions`, {action:'read'});
    this.details.replaceChildren(this.node('h3', 'Task details'));
    const output = this.node('pre', JSON.stringify({arguments:job.admission.arguments, result:job.result,
      progress:job.progress, attempts:job.attempts, operator_events:job.operator_events}, null, 2));
    this.details.append(output);
    // Resolve artifacts in the job's mode, independent of the current chat.
    window.continuationRenderer.append(this.details, '', {
      ...job.result,
      ...(job.tool === 'browser_use' && job.result?.data?.browser_research
        ? {browser_use: job.result} : {}),
      _background_mode: job.mode
    });
    if (job.state === 'needs_attention') {
      this.details.append(this.node('p', 'Reconciliation releases reserved capacity. Verify that the original operation has stopped, including at the provider for remote work. Stopping a local process is not proof of provider cancellation. This does not authorize another execution.'));
      const evidence = this.node('textarea'); evidence.minLength = 20; evidence.maxLength = 4000;
      const stopped = this.node('input'); stopped.type = 'checkbox';
      const disposition = this.node('select'); disposition.append(this.option('failed','Failed'), this.option('cancelled','Cancelled'));
      this.details.append(this.label('Termination or provider-status evidence', evidence),
        this.label('I verified the operation has stopped', stopped), this.label('Disposition', disposition),
        this.button('Record reconciliation', async () => {
          await this.act(job, 'reconcile', {evidence:evidence.value, stopped:stopped.checked, disposition:disposition.value});
          this.details.replaceChildren(this.node('p', 'Reconciliation recorded.'));
        }));
    }
    await this.refresh();
  }
};
