/** Same-origin operator controls; callback credentials never enter chat/settings exports. */
class WebhookIntegrations {
  constructor(app) {
    this.app = app;
    this.root = document.getElementById('taskIntegrations');
    if (!this.root) return;
    this.notice = this.node('p', 'Open this tab to load task callback settings.', 'setting-desc');
    this.secret = this.node('section', '', 'task-integration-secret');
    this.secret.hidden = true;
    this.content = this.node('div');
    this.root.append(this.notice, this.secret, this.content);
    document.querySelector('[data-settings-tab="integrations"]')?.addEventListener('click', () => void this.refresh());
    document.getElementById('settingsBtn')?.addEventListener('click', () => {
      if (document.getElementById('settings-integrations')?.classList.contains('active')) void this.refresh();
    });
    for (const id of ['closeSettings', 'closeSettingsBtn']) {
      document.getElementById(id)?.addEventListener('click', () => this.clearSecret());
    }
    document.querySelectorAll('[data-settings-tab]').forEach(tab => tab.addEventListener('click', () => this.clearSecret()));
    document.addEventListener('keydown', event => { if (event.key === 'Escape') this.clearSecret(); });
    document.getElementById('settingsModal')?.addEventListener('click', event => {
      if (event.target.id === 'settingsModal') this.clearSecret();
    });
  }

  node(tag, text = '', className = '') {
    const element = document.createElement(tag);
    element.textContent = text; element.className = className;
    return element;
  }

  button(text, action, disabled = false) {
    const button = this.node('button', text, 'btn-secondary');
    button.type = 'button'; button.disabled = disabled;
    button.addEventListener('click', async () => {
      button.disabled = true;
      try { await action(); } catch (error) {
        this.notice.textContent = error.message;
        Utils.toast?.(error.message, 'warning');
      }
      finally { button.disabled = disabled; }
    });
    return button;
  }

  async request(path = '', method = 'GET', body) {
    const response = await Utils.auth.fetch('/api/task-integrations' + path, {
      method, headers: {'Content-Type': 'application/json'},
      ...(body === undefined ? {} : {body: JSON.stringify(body)}), cache: 'no-store'
    });
    const value = await response.json();
    if (!response.ok) throw new Error(value.error || 'Task integration request failed');
    return value;
  }

  async refresh() {
    const revision = this.refreshRevision = (this.refreshRevision || 0) + 1;
    try {
      const data = await this.request();
      if (revision !== this.refreshRevision) return;
      this.content.replaceChildren();
      this.notice.textContent = 'Advanced callback administration. Set up and operate Browser Use from Settings → Tools. Changes here save immediately.';
      const toggle = document.createElement('input');
      toggle.type = 'checkbox'; toggle.checked = data.enabled; toggle.setAttribute('role', 'switch');
      const label = this.node('label', 'Accept incoming task callbacks', 'background-toggle');
      label.append(toggle);
      toggle.addEventListener('change', async () => {
        toggle.disabled = true;
        try { await this.request('', 'PATCH', {enabled: toggle.checked}); await this.refresh(); }
        catch (error) { toggle.checked = data.enabled; this.notice.textContent = error.message; }
        finally { toggle.disabled = false; }
      });
      const outstanding = data.sources.reduce((sum, source) => sum + source.outstanding, 0);
      this.content.append(label, this.node('p', `${outstanding} callback jobs outstanding. Turning receipt off rejects new deliveries; already accepted events can finish.`, 'setting-desc'));
      this.content.append(this.button(data.key_ready ? 'Rotate storage key' : 'Initialize credential storage', async () => {
        if (data.key_ready && !window.confirm('Rotate the credential encryption key? Back up the replacement key separately from database backups.')) return;
        await this.request('/keys', 'POST', {action: data.key_ready ? 'rotate' : 'initialize'});
        await this.refresh();
      }));
      if (!data.sources.length) this.content.append(this.node('p', 'No custom task callback sources configured.', 'setting-desc'));
      for (const source of data.sources) this.content.append(this.sourceCard(source, data.key_ready));
      this.content.append(this.sourceForm());
    } catch (error) { if (revision === this.refreshRevision) this.notice.textContent = error.message; }
  }

  field(form, label, value = '', type = 'text') {
    const wrapper = this.node('label', label, 'setting-group');
    const input = document.createElement('input');
    input.type = type; input.value = value; input.className = 'setting-input';
    input.required = true;
    wrapper.append(input); form.append(wrapper);
    return input;
  }

  sourceForm(source = null) {
    const details = document.createElement('details');
    details.append(this.node('summary', source ? 'Edit source' : 'Advanced: add custom local service'));
    const form = document.createElement('form');
    const name = this.field(form, 'Source name', source?.name || ''); name.maxLength = 100;
    const base = this.field(form, 'Jarvis API base URL (callback receiver)', source?.callback_base || 'http://127.0.0.1:8880', 'url');
    const submit = this.field(form, 'Local service submission URL', source?.submit_url || 'http://127.0.0.1:9001/submit', 'url');
    form.append(this.node('p', 'This first adapter supports a service on an explicit loopback IP. A source alone does not enable a tool; a reviewed binding is also required.', 'setting-desc'));
    const rate = this.field(form, 'Maximum new events per minute', source?.rate_limit || 60, 'number'); rate.min = 1; rate.max = 600;
    const events = this.node('fieldset'); events.append(this.node('legend', 'Accepted task events'));
    const choices = ['task.progress', 'task.completed', 'task.failed', 'task.cancelled'].map(event => {
      const check = document.createElement('input'); check.type = 'checkbox'; check.value = event;
      check.checked = source ? source.events.includes(event) : true;
      const label = this.node('label', event.replace('task.', ''), 'task-integration-event');
      label.prepend(check); events.append(label); return check;
    });
    form.append(events);
    const save = this.node('button', source ? 'Save source' : 'Create source', 'btn-secondary'); save.type = 'submit'; form.append(save);
    form.addEventListener('submit', async event => {
      event.preventDefault(); save.disabled = true;
      try {
        await this.request(source ? '/' + source.id : '', source ? 'PATCH' : 'POST', {
          ...(source ? {revision: source.revision} : {}), name: name.value, callback_base: base.value,
          submit_url: submit.value, rate_limit: Number(rate.value), events: choices.filter(item => item.checked).map(item => item.value)
        });
        await this.refresh();
      } catch (error) { this.notice.textContent = error.message; }
      finally { save.disabled = false; }
    });
    details.append(form); return details;
  }

  sourceCard(source, keyReady) {
    const card = this.node('section', '', 'task-integration-card');
    card.append(this.node('h4', source.name), this.node('p', `${source.revoked ? 'Revoked' : source.enabled ? 'Enabled' : 'Paused'} · ${source.validated ? 'Route verified' : 'Setup test required'} · ${source.outstanding} outstanding`, 'setting-desc'));
    const url = this.node('input', '', 'setting-input'); url.value = source.endpoint; url.readOnly = true;
    url.setAttribute('aria-label', 'Callback URL'); card.append(url);
    if (source.managed_tool === 'browser_use') {
      card.append(this.node('p', 'Managed from Settings → Tools → Browser use. Normal setup, testing and service controls live there.', 'setting-desc'));
      const deliveries = document.createElement('details'); deliveries.append(this.node('summary', 'Advanced delivery history'));
      const output = this.node('div'); deliveries.append(output);
      deliveries.addEventListener('toggle', () => { if (deliveries.open) void this.loadDeliveries(source, output, 0); });
      card.append(deliveries);
      return card;
    }
    const actions = this.node('div', '', 'task-integration-actions');
    const patch = changes => this.request('/' + source.id, 'PATCH', {revision: source.revision, ...changes}).then(() => this.refresh());
    actions.append(this.button('Copy URL', () => navigator.clipboard.writeText(source.endpoint)),
      this.button(source.enabled ? 'Pause source' : 'Enable source', () => patch({enabled: !source.enabled}), source.revoked));
    actions.append(this.button('Test receiver', async () => {
      const result = await this.request('/' + source.id + '/test', 'POST', {});
      await this.refresh();
      this.notice.textContent = result.message;
      Utils.toast?.(result.message, 'success');
    }, !source.enabled || source.revoked));
    actions.append(
      this.button('Revoke source', async () => {
        if (window.confirm(`Permanently revoke ${source.name}? ${source.outstanding} jobs may still be waiting. Pending evidence will be held.`)) await patch({revoke: true});
      }, source.revoked));
    card.append(actions);
    if (!source.revoked) {
      card.append(this.sourceForm(source));
      card.append(this.credentialForm(source, keyReady));
    }
    const list = this.node('div');
    for (const credential of source.credentials.filter(item => !item.probe)) {
      const expired = credential.expires_at * 1000 <= Date.now();
      const row = this.node('div', '', 'task-integration-credential');
      row.append(this.node('p', `v${credential.version} · ${credential.scheme} · ${credential.revoked_at ? 'Revoked' : expired ? 'Expired' : 'Active'} · Expires ${new Date(credential.expires_at * 1000).toLocaleString()} · Last used ${credential.last_used_at ? new Date(credential.last_used_at * 1000).toLocaleString() : 'Never'}`, 'setting-desc'));
      row.append(this.button('Rotate (5 min overlap)', () => this.createCredential(source, {scheme: credential.scheme, replace_id: credential.id, overlap_seconds: 300}), source.revoked || Boolean(credential.revoked_at) || !keyReady),
        this.button('Revoke credential', async () => {
          if (!window.confirm('Revoke this credential now? Unprocessed deliveries authenticated with it will be held.')) return;
          await this.request(`/${source.id}/credentials/${credential.id}/revoke`, 'POST', {}); await this.refresh();
        }, Boolean(credential.revoked_at)));
      list.append(row);
    }
    card.append(list);
    const deliveries = document.createElement('details'); deliveries.append(this.node('summary', 'Delivery history'));
    const output = this.node('div'); deliveries.append(output);
    deliveries.addEventListener('toggle', () => { if (deliveries.open) void this.loadDeliveries(source, output, 0); });
    card.append(deliveries); return card;
  }

  credentialForm(source, keyReady) {
    const details = document.createElement('details');
    details.append(this.node('summary', 'New credential'));
    const form = document.createElement('form');
    const label = this.node('label', 'Credential type', 'setting-group');
    const scheme = document.createElement('select'); scheme.className = 'setting-input';
    for (const [value, text] of [['bearer', 'Bearer token'], ['hmac-sha256', 'Jarvis HMAC-SHA256 (self-hosted)']]) {
      const option = this.node('option', text); option.value = value; scheme.append(option);
    }
    label.append(scheme); form.append(label);
    const days = this.field(form, 'Expires in days', 90, 'number'); days.min = 1; days.max = 365;
    const create = this.node('button', 'Create credential', 'btn-secondary'); create.type = 'submit'; create.disabled = !keyReady;
    form.append(create);
    form.addEventListener('submit', async event => {
      event.preventDefault(); create.disabled = true;
      try { await this.createCredential(source, {scheme: scheme.value, expires_in: Number(days.value) * 86400}); }
      catch (error) { this.notice.textContent = error.message; }
      finally { create.disabled = !keyReady; }
    });
    details.append(form);
    return details;
  }

  async createCredential(source, values) {
    this.clearSecret();
    const epoch = this.secretEpoch;
    const value = await this.request('/' + source.id + '/credentials', 'POST', values);
    if (epoch !== this.secretEpoch) { await this.refresh(); return; }
    this.secret.hidden = false;
    this.secret.append(this.node('h4', 'Copy this credential now'), this.node('p', 'Shown once. Store it in the sending service, never in a chat or tool argument.', 'setting-desc'));
    const text = value.authorization || `Key ID: ${value.id}\nHMAC secret: ${value.secret}`;
    const field = this.node('textarea', '', 'setting-input'); field.value = text; field.readOnly = true;
    field.setAttribute('aria-label', 'One-time credential');
    this.secret.append(field, this.button('Copy credential', () => navigator.clipboard.writeText(text)), this.button('Dismiss', () => this.clearSecret()));
    await this.refresh(); this.secret.scrollIntoView({block: 'nearest'});
  }

  clearSecret() {
    this.secretEpoch = (this.secretEpoch || 0) + 1;
    this.secret.replaceChildren(); this.secret.hidden = true;
  }

  async loadDeliveries(source, container, offset) {
    try {
      const page = await this.request(`/${source.id}/deliveries?offset=${offset}&limit=25`);
      container.replaceChildren();
      if (!page.deliveries.length) container.append(this.node('p', 'No deliveries on this page.', 'setting-desc'));
      for (const item of page.deliveries) {
        const row = this.node('div', '', 'task-integration-delivery');
        row.append(this.node('strong', `${item.event_type} · ${item.state}`), this.node('p', `${new Date(item.verified_at * 1000).toLocaleString()} · ${item.reason || 'Verified'} · Processing attempts: ${item.attempts}`, 'setting-desc'));
        row.append(this.node('p', `Event: ${item.event_id} · Job: ${item.job_id || 'Setup test'}`, 'setting-desc'));
        const details = document.createElement('details');
        details.append(this.node('summary', 'Verification details'));
        for (const [label, value] of [['Attempt', item.attempt_id], ['Credential', item.credential_id], ['Payload digest', item.payload_digest]]) {
          if (value) details.append(this.node('p', `${label}: ${value}`, 'setting-desc'));
        }
        row.append(details);
        if (item.state === 'held') row.append(this.button('Discard held event', async () => {
          if (!window.confirm(`Discard event ${item.event_id} for ${item.job_id ? 'job ' + item.job_id : 'this setup test'} without applying it to the task?`)) return;
          await this.request(`/${source.id}/deliveries/${encodeURIComponent(item.event_id)}/discard`, 'POST', {});
          await this.loadDeliveries(source, container, offset);
        }));
        container.append(row);
      }
      container.append(this.button('Previous', () => this.loadDeliveries(source, container, Math.max(0, offset - 25)), offset === 0),
        this.button('Refresh', () => this.loadDeliveries(source, container, offset)),
        this.button('Next', () => this.loadDeliveries(source, container, offset + 25), offset + 25 >= page.total));
    } catch (error) { container.textContent = error.message; }
  }
}
window.WebhookIntegrations = WebhookIntegrations;
