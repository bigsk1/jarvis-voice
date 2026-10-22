/* Lazy notification preferences and saved delivery receipts. No polling or publishing. */
(() => {
  const categories = ['alerts', 'reminders', 'background_tasks', 'notifications'];
  const names = {alerts: 'Alerts', reminders: 'Reminders', background_tasks: 'Background tasks', notifications: 'Notifications'};
  const filterValues = {mode: ['cloud', 'local'], source: ['', ...categories], channel: ['', 'ntfy'],
    state: ['', 'saved', 'pending', 'delivered', 'failed', 'suppressed', 'unavailable']};
  class NotificationsSettings {
    constructor(app) {
      this.app = app;
      this.channelState = null;
      this.channelLoading = false;
      this.saving = false;
      this.historyLoading = false;
      this.historyRequest = 0;
      this.channelRequest = 0;
      this.offset = 0;
      this.limit = 25;
      this.total = 0;
      this.items = [];
      this.enabled = this.element('notifications-enabled');
      this.fieldset = this.element('notification-category-controls');
      this.list = this.element('notification-history-list');
      this.previous = this.element('notificationsPreviousBtn');
      this.next = this.element('notificationsNextBtn');
      this.filters = Object.fromEntries(Object.keys(filterValues).map(name => [name, this.element(`notification-history-${name}`)]));
      let saved = {};
      try { saved = JSON.parse(localStorage.getItem('jarvis_notification_filters') || '{}') || {}; } catch (_) {}
      this.historyModeResolved = filterValues.mode.includes(saved.mode);
      for (const [name, control] of Object.entries(this.filters)) {
        if (!control) continue;
        const fallback = name === 'mode' && app?.socket?.mode === 'local' ? 'local' : filterValues[name][0];
        control.value = filterValues[name].includes(saved[name]) ? saved[name] : fallback;
        control.addEventListener('change', () => {
          if (name === 'mode') this.historyModeResolved = true;
          this.offset = 0; this.saveFilters(); void this.loadHistory();
        });
      }
      this.enabled?.addEventListener('change', () => this.saveChannels({enabled: this.enabled.checked}));
      for (const category of categories) {
        const control = this.element(`notifications-category-${category}`);
        control?.addEventListener('change', () => this.saveChannels({categories: {[category]: control.checked}}));
      }
      this.element('refreshNotificationsBtn')?.addEventListener('click', () => this.loadHistory());
      this.previous?.addEventListener('click', () => { if (!this.historyLoading && this.offset > 0) { this.offset = Math.max(0, this.offset - this.limit); void this.loadHistory(); } });
      this.next?.addEventListener('click', () => { if (!this.historyLoading && this.offset + this.limit < this.total) { this.offset += this.limit; void this.loadHistory(); } });
    }

    element(id) { return document.getElementById(id); }
    active() { return this.element('settingsModal')?.classList.contains('active') && this.element('settings-notifications')?.classList.contains('active'); }
    text(id, value) { const element = this.element(id); if (element) element.textContent = value; }
    saveFilters() {
      try { localStorage.setItem('jarvis_notification_filters', JSON.stringify(Object.fromEntries(Object.entries(this.filters).map(([key, control]) => [key, control?.value || ''])))); } catch (_) {}
    }
    async refresh() {
      if (!this.active()) return;
      await Promise.all([this.loadChannels(), this.loadHistory()]);
    }

    renderChannels() {
      const state = this.channelState;
      const blocked = this.channelLoading || this.saving || state?.editable !== true;
      if (this.enabled) { this.enabled.disabled = blocked; this.enabled.checked = state?.enabled === true; }
      if (this.fieldset) this.fieldset.disabled = blocked || state?.enabled !== true;
      for (const category of categories) {
        const control = this.element(`notifications-category-${category}`);
        if (control) { control.checked = state?.categories?.[category] === true; control.disabled = blocked || state?.enabled !== true; }
      }
      this.element('notification-channel-controls')?.setAttribute('aria-busy', String(this.channelLoading || this.saving));
    }

    async loadChannels() {
      if (!this.active() || this.saving) return;
      const request = ++this.channelRequest;
      this.channelLoading = true;
      this.text('notification-channels-result', 'Loading delivery preferences…');
      this.renderChannels();
      try {
        const response = await Utils.auth.fetch('/api/notifications/channels', {signal: AbortSignal.timeout(7000)});
        const data = await response.json();
        if (!response.ok || data?.ok !== true) throw new Error('Unavailable');
        if (request !== this.channelRequest) return;
        this.channelState = data;
        this.text('notification-channels-result', data.editable === true
          ? data.enabled ? 'Changes save immediately. Delivery preferences apply across modes.' : 'Phone delivery is disabled. Enable it to change categories.'
          : data.read_only === true ? 'Notification settings are read-only in this deployment. Edit the private configuration on the host.'
          : 'Configure a valid private ntfy configuration on the host to enable these controls.');
      } catch (_) {
        if (request !== this.channelRequest) return;
        this.channelState = null;
        this.text('notification-channels-result', 'Delivery preferences are unavailable. Reopen this tab to try again.');
      } finally {
        if (request === this.channelRequest) { this.channelLoading = false; this.renderChannels(); }
      }
    }

    async saveChannels(changes) {
      if (!this.active() || this.saving || this.channelLoading || this.channelState?.editable !== true) { this.renderChannels(); return; }
      this.saving = true;
      this.renderChannels();
      this.text('notification-channels-result', 'Saving delivery preferences…');
      try {
        const response = await Utils.auth.fetch('/api/notifications/channels', {
          method: 'PATCH', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(changes), signal: AbortSignal.timeout(7000)
        });
        const data = await response.json();
        if (!response.ok || data?.ok !== true) throw new Error('Unavailable');
        this.channelState = data;
        this.text('notification-channels-result', 'Saved. Delivery preferences apply across modes.');
        void this.app?.ntfyStatus?.refresh();
      } catch (_) {
        this.text('notification-channels-result', 'Could not save delivery preferences. Previous settings are shown.');
      } finally { this.saving = false; this.renderChannels(); }
    }

    async loadHistory() {
      if (!this.active()) return;
      // App state is restored after this component is constructed. Resolve
      // the initial default only when history is opened, preserving a saved
      // filter or a deliberate choice on subsequent refreshes.
      if (!this.historyModeResolved && this.filters.mode) {
        this.filters.mode.value = this.app?.socket?.mode === 'local' ? 'local' : 'cloud';
        this.historyModeResolved = true;
      }
      const request = ++this.historyRequest;
      this.historyLoading = true;
      this.text('notification-history-status', 'Loading history…');
      this.list?.setAttribute('aria-busy', 'true');
      this.renderPagination();
      const query = new URLSearchParams({limit: String(this.limit), offset: String(this.offset)});
      for (const [name, control] of Object.entries(this.filters)) if (control?.value) query.set(name === 'source' ? 'source_type' : name, control.value);
      try {
        const response = await Utils.auth.fetch(`/api/notifications?${query}`, {signal: AbortSignal.timeout(7000)});
        const data = await response.json();
        if (!response.ok || data?.ok !== true || !Array.isArray(data.items)) throw new Error('Unavailable');
        if (request !== this.historyRequest) return;
        this.items = data.items;
        this.total = Number.isSafeInteger(data.total) && data.total >= 0 ? data.total : 0;
        // A filter change or cleanup can remove the page we were viewing.
        if (this.offset > 0 && this.items.length === 0) { this.offset = 0; return this.loadHistory(); }
        this.renderHistory();
        this.text('notification-history-status', this.items.length ? '' : 'No notifications match these filters.');
      } catch (_) {
        if (request !== this.historyRequest) return;
        this.items = []; this.total = 0;
        this.renderHistory();
        this.text('notification-history-status', 'History is unavailable. Use Refresh history to try again.');
      } finally {
        if (request === this.historyRequest) { this.historyLoading = false; this.list?.setAttribute('aria-busy', 'false'); this.renderPagination(); }
      }
    }

    renderHistory() {
      if (!this.list) return;
      this.list.replaceChildren();
      for (const item of this.items) {
        const row = document.createElement('article'); row.className = 'notification-history-item';
        const heading = document.createElement('h4'); heading.textContent = String(item.title || names[item.source_type] || item.source || 'Notification');
        row.appendChild(heading);
        const details = document.createElement('p'); details.className = 'notification-history-meta';
        let time = 'Time unavailable';
        if (item.created_at && Number.isFinite(Date.parse(item.created_at))) time = new Date(item.created_at).toLocaleString();
        else {
          const sent = (Array.isArray(item.deliveries) ? item.deliveries : []).find(delivery => delivery.sent_at && Number.isFinite(Date.parse(delivery.sent_at)));
          if (sent) time = `Accepted ${new Date(sent.sent_at).toLocaleString()}`;
        }
        details.textContent = [names[item.source_type] || 'Notification', item.source || '', time].filter(Boolean).join(' · ');
        row.appendChild(details);
        if (item.message) { const body = document.createElement('p'); body.className = 'notification-history-message'; body.textContent = String(item.message); row.appendChild(body); }
        const deliveries = Array.isArray(item.deliveries) ? item.deliveries : [];
        const receipt = document.createElement('p'); receipt.className = 'notification-history-delivery';
        receipt.textContent = deliveries.length ? deliveries.map(delivery => {
          const state = String(delivery.state || 'unknown');
          return `${delivery.channel || 'Delivery'}: ${state === 'delivered' ? 'accepted by service' : state}${delivery.error ? ` — ${delivery.error}` : ''}`;
        }).join(' · ') : 'Saved locally';
        row.appendChild(receipt); this.list.appendChild(row);
        if (item.source_id != null) {
          const reference = document.createElement('p'); reference.className = 'notification-history-meta';
          reference.textContent = `Source reference: ${item.source_id}`;
          const target = this.sourceLink(item);
          if (target) {
            const link = document.createElement('a');
            link.href = target; link.target = '_blank'; link.rel = 'noopener noreferrer';
            link.textContent = `View ${names[item.source_type].toLowerCase()}`;
            reference.appendChild(document.createTextNode(' · ')); reference.appendChild(link);
          }
          row.appendChild(reference);
        }
      }
    }

    sourceLink(item) {
      if (!['alerts', 'reminders'].includes(item.source_type)) return null;
      try {
        const fallback = new URL(window.location?.href || 'http://localhost');
        fallback.protocol = 'http:'; fallback.port = '5002'; fallback.pathname = '/'; fallback.search = ''; fallback.hash = '';
        const configured = window.JarvisUINavigation?.url('memory', fallback.href) || fallback.href;
        const target = new URL(configured);
        if (!['http:', 'https:'].includes(target.protocol) || target.username || target.password) return null;
        target.searchParams.set('mode', item.mode === 'local' ? 'local' : 'cloud');
        target.hash = item.source_type;
        return target.href;
      } catch (_) { return null; }
    }

    renderPagination() {
      if (this.previous) this.previous.disabled = this.historyLoading || this.offset === 0;
      if (this.next) this.next.disabled = this.historyLoading || this.offset + this.limit >= this.total;
      this.element('refreshNotificationsBtn')?.toggleAttribute('disabled', this.historyLoading);
      this.text('notification-history-page', this.total ? `${this.offset + 1}–${Math.min(this.offset + this.items.length, this.total)} of ${this.total}` : '0 items');
    }
  }
  window.NotificationsSettings = NotificationsSettings;
})();
