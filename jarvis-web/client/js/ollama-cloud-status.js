/** Read-only account balance and activity for the selected Ollama Cloud account. */
class OllamaCloudStatus {
  constructor(app) {
    this.app = app;
    this.generation = 0;
    this.controller = null;
  }

  mode() {
    return this.app._settingsData?.mode || this.app.socket.mode;
  }

  async load() {
    const el = document.getElementById('ollama-cloud-status');
    const mode = this.mode();
    if (!el || mode !== 'cloud') return;

    const generation = ++this.generation;
    const settings = this.app._settingsData;
    this.controller?.abort();
    const controller = new AbortController();
    this.controller = controller;
    const timeout = setTimeout(() => controller.abort(), 30000);
    const current = () => generation === this.generation
      && document.getElementById('ollama-cloud-status') === el
      && this.mode() === mode && this.app._settingsData === settings;

    try {
      const response = await Utils.auth.fetch(`/api/ollama/cloud-status?mode=${mode}`, {
        signal: controller.signal
      });
      if (!response.ok) throw new Error('Account status unavailable');
      const data = await response.json();
      if (!current()) return;
      if (!data || typeof data !== 'object' || data.ok === false) {
        throw new Error('Account status unavailable');
      }
      this.render(el, data);
      this.updateAvailability(data);
    } catch (_) {
      if (!current()) return;
      this.render(el, null);
    } finally {
      clearTimeout(timeout);
      if (this.controller === controller) this.controller = null;
    }
  }

  number(value) {
    return typeof value === 'number' && Number.isFinite(value) && value >= 0;
  }

  money(value) {
    if (value > 0 && value < 0.00001) return '< $0.00001';
    return value.toLocaleString(undefined, {
      style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 5
    });
  }

  date(value) {
    if (typeof value !== 'string' || !Number.isFinite(Date.parse(value))) return null;
    return new Date(value).toLocaleString(undefined, {dateStyle: 'medium', timeStyle: 'short'});
  }

  accountLink(value) {
    try {
      const url = new URL(value);
      if (url.protocol === 'https:' && url.hostname === 'ollama.com'
          && !url.port && !url.username && !url.password) return url.href;
    } catch (_) { /* Untrusted or missing account URL. */ }
    return null;
  }

  render(el, data) {
    const label = document.createElement('span');
    label.className = 'config-label';
    label.textContent = 'Ollama Cloud';
    const values = document.createElement('span');
    values.className = 'config-value config-value-list';
    const line = (text, status = '') => {
      const row = document.createElement('span');
      row.className = `config-value-list-item${status ? ` ${status}` : ''}`;
      row.textContent = text;
      values.appendChild(row);
      return row;
    };

    if (!data) {
      line('Account status unavailable', 'error');
      el.title = '';
      el.replaceChildren(label, values);
      return;
    }

    const direct = data.connection_mode === 'api_key';
    let status = 'Account status unavailable';
    let statusClass = 'usage-warning';
    if (data.reachable === false) {
      status = 'Account service unreachable';
      statusClass = 'usage-critical';
    } else if (data.signed_in === false) {
      status = direct ? 'API key rejected' : 'Not signed in';
    } else if (data.signed_in === true) {
      status = direct ? 'API key verified' : 'Signed in';
      statusClass = 'usage-ok';
    }
    if (typeof data.plan === 'string' && data.plan.trim()) status += ` · ${data.plan}`;
    const account = line(status, statusClass);
    const signin = data.signed_in === false && this.accountLink(data.signin_url);
    const url = signin || this.accountLink(data.dashboard_url) || 'https://ollama.com/settings';
    const link = document.createElement('a');
    link.href = url;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.textContent = signin ? 'Sign in' : 'Manage';
    account.appendChild(document.createTextNode(' · '));
    account.appendChild(link);

    const unavailable = (name, result) => {
      const reasons = {
        unsupported: 'not supported by this host', unauthorized: 'access denied',
        rate_limited: 'temporarily rate limited', invalid: 'unavailable', unavailable: 'unavailable'
      };
      line(`${name}: ${reasons[result?.status] || 'unavailable'}`);
    };
    const balance = data.balance?.status === 'available' ? data.balance.data : null;
    let balanceLines = 0;
    if (balance && typeof balance === 'object') {
      const included = balance.included || {};
      if (this.number(included.balance_usd)) {
        const allowance = this.number(included.allowance_usd)
          ? ` of ${this.money(included.allowance_usd)}` : '';
        line(`Included: ${this.money(included.balance_usd)} remaining${allowance}`);
        balanceLines++;
      } else if (this.number(included.allowance_usd)) {
        line(`Included allowance: ${this.money(included.allowance_usd)} · remaining unavailable`);
        balanceLines++;
      }
      const renewal = this.date(included.period?.until);
      if (renewal) line(`Included credits renew: ${renewal}`);
      for (const [name, key] of [['Session', 'session'], ['Weekly', 'weekly']]) {
        const quota = included[key];
        if (!this.number(quota?.remaining_percent) || quota.remaining_percent > 100) continue;
        const reset = this.date(quota.resets_at);
        line(`${name}: ${quota.remaining_percent.toLocaleString()}% remaining${reset ? ` · resets ${reset}` : ''}`);
        balanceLines++;
      }
      if (this.number(balance.purchased?.balance_usd)) {
        line(`Purchased: ${this.money(balance.purchased.balance_usd)} remaining`);
        balanceLines++;
      }
    }
    if (!balanceLines) unavailable('Balance', data.balance);

    const usage = data.usage?.status === 'available' ? data.usage.data : null;
    const totals = usage?.totals || {};
    const activity = [];
    if (this.number(totals.request_count)) activity.push(`${totals.request_count.toLocaleString()} requests`);
    if (this.number(totals.usage_usd)) activity.push(`${this.money(totals.usage_usd)} usage`);
    if (activity.length) line(`Last 7 days: ${activity.join(' · ')}`);
    const tokens = [];
    for (const [name, key] of [['input', 'input_tokens'], ['cached input', 'cached_input_tokens'], ['output', 'output_tokens']]) {
      if (this.number(totals[key])) tokens.push(`${totals[key].toLocaleString()} ${name}`);
    }
    if (tokens.length) line(`Tokens (7 days): ${tokens.join(' · ')}`);
    if (!activity.length && !tokens.length) unavailable('7-day usage', data.usage);
    if (activity.length || tokens.length) line('Usage reporting may be delayed');

    const checked = this.date(data.checked_at);
    el.title = `${direct ? 'Ollama API key' : 'Signed-in Ollama host'}${checked ? ` · Checked ${checked}` : ''}`;
    el.replaceChildren(label, values);
  }

  updateAvailability(data) {
    if (this.mode() !== 'cloud' || !this.app._settingsData?.provider_availability) return;
    let resolved;
    if (data.signed_in === false) {
      resolved = {status: 'unavailable', reason: data.connection_mode === 'api_key'
        ? 'Ollama API key rejected' : 'Ollama host not signed in'};
    } else if (data.signed_in === true) {
      resolved = {status: 'available', reason: null};
    } else {
      // Account endpoint outages do not establish inference availability.
      return;
    }
    for (const domain of ['llm', 'completion_guard']) {
      const map = this.app._settingsData.provider_availability[domain];
      if (map?.ollama) map.ollama = {...resolved};
    }
    this.app._applyProviderAvailability('setting-llm-provider', 'llm');
    this.app._applyProviderAvailability('setting-completion-guard-eval-provider', 'completion_guard');
  }
}

window.OllamaCloudStatus = OllamaCloudStatus;
