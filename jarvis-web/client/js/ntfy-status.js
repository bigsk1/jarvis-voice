/* Optional phone-notification diagnostics, loaded only when Profile is opened. */
(() => {
  class NtfyStatusCard {
    constructor() {
      this.card = document.getElementById('ntfy-status');
      this.label = document.getElementById('ntfy-status-label');
      this.detail = document.getElementById('ntfy-status-detail');
      this.result = document.getElementById('ntfy-test-result');
      this.refreshButton = document.getElementById('refreshNtfyStatusBtn');
      this.testButton = document.getElementById('testNtfyBtn');
      this.requestId = 0;
      this.loading = false;
      this.testing = false;
      this.status = null;
      this.error = false;
      this.refreshButton?.addEventListener('click', () => this.refresh());
      this.testButton?.addEventListener('click', () => this.sendTest());
    }

    active() {
      return document.getElementById('settingsModal')?.classList.contains('active')
        && document.getElementById('settings-profile')?.classList.contains('active');
    }

    presentation() {
      if (this.loading) return ['Checking…', 'Checking configuration, worker, and ntfy server…', 'neutral'];
      if (this.error) return ['Unavailable', 'Could not check ntfy. Try Refresh.', 'warning'];
      const status = this.status;
      if (!status) return ['Not checked', 'Open Profile to check phone notifications.', 'neutral'];
      if (status.configuration === 'missing') return ['Not configured', 'Phone notifications are optional. Configure ntfy to enable them.', 'neutral'];
      if (status.configuration === 'disabled') return ['Disabled', 'Phone notifications are disabled in the ntfy configuration.', 'neutral'];
      if (status.configuration !== 'enabled') return ['Invalid configuration', 'Check the ntfy configuration and its file permissions.', 'warning'];
      const names = {alerts: 'alerts', reminders: 'reminders', background_tasks: 'background tasks'};
      const categories = (Array.isArray(status.categories) ? status.categories : [])
        .map(name => names[name]).filter(Boolean);
      const enabled = categories.length ? `Enabled: ${categories.join(', ')}.` : 'No notification categories enabled.';
      const worker = status.worker || {};
      const mode = worker.mode === 'local' ? 'Local' : worker.mode === 'cloud' ? 'Cloud' : '';
      const descriptions = {
        ready: `Worker running${mode ? ` (${mode})` : ''}.`,
        checking: `Worker checking events${mode ? ` (${mode})` : ''}.`,
        disabled: 'Worker has not picked up the enabled configuration yet.',
        degraded: 'Worker needs attention; check notification logs.',
        stopped: 'Notification worker is stopped.',
        stale: 'Worker status is stale; refresh or check services.',
        unknown: 'Worker status has not been reported; check services.'
      };
      const detail = `${status.server_online === true ? 'Configured; server online.' : 'Configured; server unreachable.'} ${descriptions[worker.state] || descriptions.unknown} ${enabled}`;
      if (status.server_online !== true) return ['Server unreachable', detail, 'warning'];
      if (!['ready', 'checking'].includes(worker.state)) return ['Check worker', detail, 'warning'];
      return ['Online', detail, categories.length ? 'positive' : 'neutral'];
    }

    render() {
      if (!this.card || !this.label || !this.detail || !this.refreshButton || !this.testButton) return;
      const [label, detail, tone] = this.presentation();
      this.label.textContent = label;
      this.detail.textContent = detail;
      this.card.dataset.tone = tone;
      this.card.setAttribute('aria-busy', String(this.loading || this.testing));
      this.refreshButton.disabled = this.loading || this.testing;
      this.testButton.disabled = this.loading || this.testing || this.error || this.status?.test_available !== true;
      this.testButton.textContent = this.testing ? 'Sending…' : 'Send test';
    }

    async refresh() {
      if (!this.active() || this.testing) return;
      const requestId = ++this.requestId;
      this.loading = true;
      this.error = false;
      this.status = null;
      if (this.result) this.result.textContent = '';
      this.render();
      try {
        const response = await Utils.auth.fetch('/api/ntfy/status', {signal: AbortSignal.timeout(7000)});
        const data = await response.json();
        if (!response.ok || data?.ok !== true) throw new Error('Status unavailable');
        if (requestId === this.requestId) this.status = data;
      } catch (_) {
        if (requestId === this.requestId) this.error = true;
      } finally {
        if (requestId === this.requestId) { this.loading = false; this.render(); }
      }
    }

    async sendTest() {
      if (!this.active() || this.loading || this.testing || this.status?.test_available !== true) return;
      this.testing = true;
      if (this.result) this.result.textContent = 'Sending a test notification…';
      this.render();
      try {
        const response = await Utils.auth.fetch('/api/ntfy/test', {
          method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}',
          signal: AbortSignal.timeout(12000)
        });
        const data = await response.json();
        if (this.result) this.result.textContent = response.ok && data?.ok === true
          ? 'Test accepted by ntfy. Check your phone for “Jarvis notification test”.'
          : response.status === 429 ? 'Wait 30 seconds before sending another test.'
          : response.status === 409 ? 'Enable ntfy and a notification category first, then Refresh.'
          : 'Test was not confirmed. Check the server and publisher credentials.';
      } catch (_) {
        if (this.result) this.result.textContent = 'Test was not confirmed. Check the connection before trying again.';
      } finally {
        this.testing = false;
        this.render();
      }
    }
  }
  window.NtfyStatusCard = NtfyStatusCard;
})();
