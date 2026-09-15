"""Read-only Profile status must describe this browser's verified connection."""

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

HARNESS = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
class Element {
  constructor() {
    this.dataset = {}; this.events = {}; this.attributes = {}; this.textContent = '';
    const classes = new Set();
    this.classList = {
      add: value => classes.add(value), remove: value => classes.delete(value),
      contains: value => classes.has(value),
      toggle(value, enabled) {
        const add = enabled === undefined ? !classes.has(value) : enabled;
        if (add) classes.add(value); else classes.delete(value);
      }
    };
  }
  addEventListener(name, handler) { (this.events[name] ||= []).push(handler); }
  setAttribute(name, value) { this.attributes[name] = value; }
  click() { for (const handler of this.events.click || []) handler({target: this}); }
  set innerHTML(_) { throw new Error('Status rendering must use textContent'); }
}
const elements = Object.fromEntries([
  'tailscale-status', 'tailscale-status-label', 'tailscale-status-detail', 'refreshTailscaleStatusBtn',
  'settingsModal', 'settings-profile', 'settings-general', 'settingsBtn', 'closeSettings',
  'closeSettingsBtn', 'modeSelect', 'audioToggle', 'newChatBtn', 'statusDot', 'statusText'
].map(id => [id, new Element()]));
const tabs = ['general', 'profile'].map(name => {
  const tab = new Element(); tab.dataset.settingsTab = name; return tab;
});
const requests = [], generalRequests = [], pending = [], timeouts = [];
const sandbox = {
  URL, console,
  AbortSignal: {timeout(milliseconds) {
    const controller = new AbortController();
    timeouts.push({milliseconds, controller});
    return controller.signal;
  }},
  window: {location: new URL('https://jarvis.example.test')},
  document: {
    getElementById: id => elements[id] || null,
    querySelectorAll: selector => selector === '.settings-tab' ? tabs
      : selector === '.settings-panel' ? [elements['settings-general'], elements['settings-profile']] : [],
    addEventListener() {}
  },
  Utils: {auth: {fetch: (url, options) => {
    requests.push(url);
    assert.ok(options.signal, 'Every probe must have a transport timeout');
    return new Promise((resolve, reject) => {
      pending.push({resolve, reject});
      options.signal.addEventListener('abort', () => reject(options.signal.reason), {once: true});
    });
  }}},
  fetch: async url => {
    generalRequests.push(url);
    return {ok: true, json: async () => ({version: 'test', features: {auth: true}})};
  },
  setTimeout() { throw new Error('Tailscale status must not poll in the background'); },
  setInterval() { throw new Error('Tailscale status must not poll in the background'); }
};
vm.createContext(sandbox);
const source = fs.readFileSync(ROOT + '/jarvis-web/client/js/app.js', 'utf8');
const JarvisApp = vm.runInContext(source.slice(0, source.lastIndexOf('// Initialize app')) + '\nJarvisApp;', sandbox);
const app = Object.create(JarvisApp.prototype);
for (const id of ['settingsModal', 'settingsBtn', 'closeSettings', 'closeSettingsBtn', 'modeSelect',
  'audioToggle', 'newChatBtn', 'statusDot', 'statusText']) app[id] = elements[id];
app.socket = {mode: 'cloud', connect() {}};
app._connectionConnected = true;
app._tailscaleRequestId = 0;
app._syncJarvisHudLogo = () => {};
app._loadSettings = () => {};
app._loadUserProfileSummary = () => {};
function profileVisible() {
  elements.settingsModal.classList.add('active');
  elements['settings-profile'].classList.add('active');
}
const running = {
  ok: true, deployment: 'native', state: 'running', backend_state: 'Running',
  hostname: 'jarvis.example.test', online: true,
  serve: {state: 'configured', listeners: [
    {hostname: 'jarvis.example.test', port: 443, https: true, funnel: false}
  ]}, checked_at: 1, cached: false
};
const response = value => ({ok: true, json: async () => value});
const flush = () => new Promise(resolve => setImmediate(resolve));
"""


def run_browser(body):
    script = f"const ROOT = {json.dumps(str(ROOT))};\n" + HARNESS
    script += "\n(async () => {\n" + body + "\n})().catch(error => {console.error(error); process.exit(1);});"
    result = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr


def test_private_status_requires_verified_matching_https_listener_and_online_chat():
    run_browser(r"""
function view(status = running, url = 'https://jarvis.example.test', connected = true) {
  return app._getTailscalePresentation(status, new URL(url), connected);
}
assert.equal(view().label, 'Connected');
assert.equal(view().tone, 'positive');
assert.equal(view().detail, 'Private Tailscale HTTPS.');
assert.equal(view(running, 'https://JARVIS.EXAMPLE.TEST.:443').label, 'Connected');
assert.equal(view(running, 'https://jarvis.example.test', false).label, 'Reconnecting');
assert.equal(view(running, 'https://jarvis.example.test', false).tone, 'warning');
assert.equal(view(running, 'http://jarvis.example.test:5001').label, 'Not in use');
assert.equal(view(running, 'https://jarvis.example.test:8443').label, 'Not in use');
assert.equal(view(running, 'https://other.example.test').label, 'Not in use');
const alternatePort = structuredClone(running);
alternatePort.serve.listeners[0].port = 8443;
assert.equal(view(alternatePort, 'https://jarvis.example.test:8443').label, 'Connected');
assert.equal(view({...running, online: false}).label, 'Disconnected');
assert.equal(view({...running, online: null}).label, 'Unverified');
assert.equal(view({...running, online: 'true'}).label, 'Unverified');
assert.equal(view({...running, deployment: 'unknown'}).label, 'Unverified');

const publicStatus = structuredClone(running);
publicStatus.serve.listeners[0].funnel = true;
assert.equal(view(publicStatus).label, 'Public HTTPS');
assert.equal(view(publicStatus).tone, 'warning');
publicStatus.serve.state = 'unavailable';
publicStatus.serve.listeners.push(null);
assert.equal(view(publicStatus).label, 'Public HTTPS', 'Other malformed metadata must not hide verified Funnel exposure');
for (const exposure of [null, undefined, 'false', 0]) {
  const unknown = structuredClone(running);
  unknown.serve.listeners[0].funnel = exposure;
  assert.equal(view(unknown).label, 'Unverified');
}
const duplicateUnknown = structuredClone(running);
duplicateUnknown.serve.listeners.push({...duplicateUnknown.serve.listeners[0], funnel: null});
assert.equal(view(duplicateUnknown).label, 'Unverified');
for (const invalid of [null, {hostname: 'jarvis.example.test', port: '443', https: true, funnel: false},
  {hostname: 'jarvis.example.test', port: 443, https: false, funnel: false}]) {
  assert.equal(view({...running, serve: {state: 'configured', listeners: [invalid]}}).label, 'Unverified');
}
assert.equal(view({...running, serve: {state: 'unavailable', listeners: running.serve.listeners}}).label, 'Unverified');
assert.equal(view({...running, serve: {state: 'not_configured', listeners: []}}).label, 'Not in use');
assert.equal(requests.length, 0);
""")


def test_unavailable_native_and_docker_states_do_not_claim_host_or_private_connectivity():
    run_browser(r"""
const presentation = value => app._getTailscalePresentation({...running, ...value});
assert.equal(presentation({state: 'not_installed'}).label, 'Not enabled');
assert.equal(presentation({state: 'not_installed'}).tone, 'neutral');
assert.equal(presentation({state: 'stopped'}).label, 'Disconnected');
for (const state of ['not_installed', 'unavailable']) {
  const view = presentation({deployment: 'docker', state});
  assert.equal(view.label, 'Unverified');
  assert.equal(view.detail, 'Host status is unavailable from this container.');
}
assert.match(presentation({state: 'unavailable'}).detail, /This page uses HTTPS/);
assert.equal(presentation({state: '<img src=x onerror=alert(1)>'}).label, 'Unverified');
app._tailscaleStatus = {...running, state: 'unavailable', error_code: '<script>secret</script>'};
app._renderTailscaleStatus();
assert.equal(elements['tailscale-status-label'].textContent, 'Unverified');
assert.ok(!elements['tailscale-status-detail'].textContent.includes('script'));
assert.equal(elements['tailscale-status'].dataset.tone, 'neutral');
""")


def test_requests_are_lazy_authenticated_and_only_profile_open_or_refresh_triggers_them():
    run_browser(r"""
for (const method of ['_setupSocketListeners', '_setupHudLogo', '_restoreState', '_applyGlowIntensity',
  '_updateSpeakerButton', '_loadConversationHistory']) app[method] = () => {};
app._initialize();
assert.equal(requests.length, 0, 'App startup must not probe Tailscale');
elements.settingsBtn.click();
assert.equal(requests.length, 0, 'Opening another settings tab must not probe Tailscale');
await app._updateProfileSection({mode: 'cloud'});
assert.deepEqual(generalRequests, ['/api/status']);
assert.equal(requests.length, 0, 'General status updates must not trigger a Tailscale probe');
await app._loadTailscaleStatus();
assert.equal(requests.length, 0, 'A hidden Profile panel must not probe Tailscale');
tabs[1].click();
assert.deepEqual(requests, ['/api/tailscale/status']);
assert.equal(elements['tailscale-status-label'].textContent, 'Checking…');
assert.equal(elements.refreshTailscaleStatusBtn.disabled, true);
pending.shift().resolve(response(running));
await flush();
assert.equal(elements['tailscale-status-label'].textContent, 'Connected');
assert.equal(elements.refreshTailscaleStatusBtn.disabled, false);
app._updateConnectionStatus(false);
assert.equal(elements['tailscale-status-label'].textContent, 'Reconnecting');
app._updateConnectionStatus(true);
assert.equal(elements['tailscale-status-label'].textContent, 'Connected');
assert.equal(requests.length, 1, 'Chat connection events may rerender but must not probe');
elements.closeSettings.click();
await app._loadTailscaleStatus();
assert.equal(requests.length, 1, 'Closed settings must not probe');
elements.settingsBtn.click();
assert.equal(requests.length, 2, 'Reopening Settings on Profile must check again');
pending.shift().resolve(response(running));
await flush();
elements.refreshTailscaleStatusBtn.click();
assert.equal(requests.length, 3);
assert.ok(requests.every(url => url === '/api/tailscale/status'), 'Refresh must not bypass server caching');
assert.ok(timeouts.every(timeout => timeout.milliseconds === 7000));
pending.shift().resolve(response(running));
await flush();
""")


def test_stale_refresh_responses_cannot_replace_newer_status_or_clear_checking():
    run_browser(r"""
profileVisible();
const older = app._loadTailscaleStatus();
const newer = app._loadTailscaleStatus();
pending[0].resolve(response(running));
await older;
assert.equal(elements['tailscale-status-label'].textContent, 'Checking…');
assert.equal(elements.refreshTailscaleStatusBtn.disabled, true);
pending[1].resolve(response({...running, state: 'stopped'}));
await newer;
assert.equal(elements['tailscale-status-label'].textContent, 'Disconnected');
assert.equal(elements['tailscale-status'].attributes['aria-busy'], 'false');

const staleFailure = app._loadTailscaleStatus();
const latest = app._loadTailscaleStatus();
pending[3].resolve(response(running));
await latest;
pending[2].reject(new Error('private failure details'));
await staleFailure;
assert.equal(elements['tailscale-status-label'].textContent, 'Connected');
assert.equal(elements.refreshTailscaleStatusBtn.disabled, false);
""")


def test_failed_refresh_clears_old_success_and_offers_safe_retry():
    run_browser(r"""
profileVisible();
app._tailscaleStatus = running;
app._renderTailscaleStatus();
const denied = app._loadTailscaleStatus();
assert.equal(elements['tailscale-status-label'].textContent, 'Checking…');
assert.equal(elements['tailscale-status'].dataset.tone, 'neutral');
pending[0].resolve({ok: false, json: async () => ({ok: false, error: 'secret endpoint details'})});
await denied;
assert.equal(elements['tailscale-status-label'].textContent, 'Unavailable');
assert.equal(elements.refreshTailscaleStatusBtn.disabled, false);
assert.equal(app._tailscaleStatus, null);
assert.ok(!elements['tailscale-status-detail'].textContent.includes('secret'));
const invalidJson = app._loadTailscaleStatus();
pending[1].resolve({ok: true, json: async () => {throw new Error('invalid JSON');}});
await invalidJson;
assert.equal(elements['tailscale-status-label'].textContent, 'Unavailable');
const retry = app._loadTailscaleStatus();
pending[2].resolve(response(running));
await retry;
assert.equal(elements['tailscale-status-label'].textContent, 'Connected');
""")


def test_hung_request_times_out_and_refresh_becomes_available():
    run_browser(r"""
profileVisible();
const hung = app._loadTailscaleStatus();
assert.equal(elements.refreshTailscaleStatusBtn.disabled, true);
assert.equal(timeouts[0].milliseconds, 7000);
timeouts[0].controller.abort(new Error('Timeout'));
await hung;
assert.equal(elements['tailscale-status-label'].textContent, 'Unavailable');
assert.equal(elements.refreshTailscaleStatusBtn.disabled, false);
assert.equal(elements['tailscale-status'].attributes['aria-busy'], 'false');
""")
