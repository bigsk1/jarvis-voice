import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

HARNESS = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
class Element {
  constructor() { this.textContent = ''; this.dataset = {}; this.disabled = false; this.events = {};
    this.attributes = {}; this.active = false; this.classList = {contains: () => this.active}; }
  setAttribute(key, value) { this.attributes[key] = value; }
  addEventListener(key, callback) { this.events[key] = callback; }
  set innerHTML(value) { throw new Error('Use textContent for diagnostics'); }
}
const elements = Object.fromEntries(['settingsModal', 'settings-profile', 'ntfy-status',
  'ntfy-status-label', 'ntfy-status-detail', 'ntfy-test-result', 'refreshNtfyStatusBtn', 'testNtfyBtn']
  .map(id => [id, new Element()]));
const calls = [], pending = [];
const sandbox = {console, window: {}, AbortSignal,
  document: {getElementById: id => elements[id]},
  Utils: {auth: {fetch(url, options) {
    calls.push({url, options});
    assert.ok(options.signal);
    return new Promise((resolve, reject) => pending.push({resolve, reject}));
  }}}};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(ROOT + '/jarvis-web/client/js/ntfy-status.js', 'utf8'), sandbox);
const card = new sandbox.window.NtfyStatusCard();
const ready = {ok: true, configuration: 'enabled', enabled: true, configured: true,
  server_online: true, worker: {state: 'ready', mode: 'cloud'},
  categories: ['alerts', 'reminders'], test_available: true};
const answer = data => ({ok: true, status: 200, json: async () => data});
(async () => {
  await card.refresh();
  assert.equal(calls.length, 0, 'No diagnostics until Profile is visible');
  elements.settingsModal.active = elements['settings-profile'].active = true;
  let refresh = card.refresh();
  assert.equal(elements['ntfy-status-label'].textContent, 'Checking…');
  assert.equal(elements.testNtfyBtn.disabled, true);
  pending.shift().resolve(answer(ready)); await refresh;
  assert.equal(elements['ntfy-status-label'].textContent, 'Online');
  assert.match(elements['ntfy-status-detail'].textContent, /Cloud/);
  assert.equal(elements.testNtfyBtn.disabled, false);
  assert.equal(calls.length, 1, 'Opening Profile must not send a test');

  const testing = card.sendTest(); await card.sendTest();
  assert.equal(calls.length, 2, 'Double click must not duplicate a publish');
  assert.equal(calls[1].url, '/api/ntfy/test');
  assert.equal(calls[1].options.method, 'POST');
  assert.equal(calls[1].options.body, '{}');
  assert.equal(elements.testNtfyBtn.disabled, true);
  pending.shift().resolve(answer({ok: true})); await testing;
  assert.match(elements['ntfy-test-result'].textContent, /accepted by ntfy.*Check your phone/);
  assert.equal(elements.testNtfyBtn.disabled, false);

  refresh = card.refresh();
  pending.shift().resolve(answer({...ready, configuration: 'disabled', enabled: false, test_available: false}));
  await refresh;
  assert.equal(elements['ntfy-status-label'].textContent, 'Disabled');
  assert.equal(elements.testNtfyBtn.disabled, true);
  assert.equal(elements['ntfy-test-result'].textContent, '');
  await card.sendTest(); assert.equal(calls.length, 3);

  const older = card.refresh(), newest = card.refresh();
  const oldRequest = pending.shift(), newRequest = pending.shift();
  newRequest.resolve(answer({...ready, worker: {state: 'stale', mode: 'local'}})); await newest;
  oldRequest.reject(new Error('private detail')); await older;
  assert.equal(elements['ntfy-status-label'].textContent, 'Check worker');
  assert.equal(elements['ntfy-status'].dataset.tone, 'warning');
  assert.ok(!elements['ntfy-status-detail'].textContent.includes('private'));

  refresh = card.refresh(); pending.shift().resolve({ok: false, json: async () => ({error: 'private token'})});
  await refresh;
  assert.equal(elements['ntfy-status-label'].textContent, 'Unavailable');
  assert.equal(elements.testNtfyBtn.disabled, true);
  assert.ok(!elements['ntfy-status-detail'].textContent.includes('token'));
  refresh = card.refresh(); pending.shift().resolve(answer(ready)); await refresh;
  const failedTest = card.sendTest();
  pending.shift().resolve({ok: false, status: 502, json: async () => ({ok: false, error: 'private token'})});
  await failedTest;
  assert.ok(!elements['ntfy-test-result'].textContent.includes('private'));
  console.log('ntfy UI lifecycle passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
"""


def test_ntfy_card_lifecycle():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is needed for the browser component harness')
    result = subprocess.run([node, '-e', 'const ROOT = ' + repr(str(ROOT)) + ';\n' + HARNESS],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr


def test_ntfy_card_is_loaded_before_app_and_below_tailscale():
    html = (ROOT / 'jarvis-web/client/index.html').read_text()
    assert html.index('id="tailscale-status"') < html.index('id="ntfy-status"') < html.index('id="user-profile-summary"')
    assert html.index('/js/ntfy-status.js') < html.index('/js/app.js')
