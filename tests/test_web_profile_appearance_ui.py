"""Exercise appearance editing and async load/save boundaries without live storage."""

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
class Element {
  constructor() { this.value = ''; this.listeners = {}; this.textContent = ''; this.files = []; }
  addEventListener(name, fn) { this.listeners[name] = fn; }
  getAttribute() { return '/assets/jarvis-voice.png'; }
  reportValidity() { return true; }
  fire(name) { return this.listeners[name]?.(); }
  click() { return this.fire('click'); }
  set innerHTML(_) { throw new Error('Profile identity must stay inert text'); }
}
const elements = new Map();
const get = id => { if (!elements.has(id)) elements.set(id, new Element()); return elements.get(id); };
const requests = [], pending = [], revoked = [];
const sandbox = {window: {}, document: {getElementById: get}, FormData, URL: {
  createObjectURL: () => 'blob:local-preview', revokeObjectURL: url => revoked.push(url),
}, fetch: (url, init = {}) => {
  requests.push({url, init});
  return new Promise(resolve => pending.push(resolve));
}};
vm.runInNewContext(fs.readFileSync(ROOT + '/jarvis-web/client/js/profile-appearance.js', 'utf8'), sandbox);
const appearance = new sandbox.window.ProfileAppearance();
const reply = (index, profile, ok = true) => pending[index]({ok, json: async () => ({ok, profile, error: ok ? null : 'Synthetic failure'})});
const profile = {display_name: 'Morgan', avatar: null};
const flush = () => new Promise(resolve => setImmediate(resolve));
async function load() { const done = appearance.load(); reply(requests.length - 1, profile); await done; }
"""


def run_browser(body):
    script = f'const ROOT = {json.dumps(str(ROOT))};\n' + HARNESS
    script += '\n(async () => {\n' + body + '\n})().catch(error => {console.error(error); process.exit(1);});'
    result = subprocess.run(['node', '-e', script], cwd=ROOT, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr


def test_preview_save_failure_retry_and_restore_default():
    run_browser(r"""
await load();
get('profileDisplayName').value = 'Alex <b>literal</b>';
get('profileDisplayName').fire('input');
appearance.selectFile(new File(['synthetic pixels'], 'avatar.png', {type: 'image/png'}));
assert.equal(get('profileAvatar').src, 'blob:local-preview');
assert.equal(get('profileDisplayLabel').textContent, 'Alex <b>literal</b>');
assert.equal(requests.length, 1, 'Previewing must never upload');
const failure = appearance.save();
assert.equal(get('profileDisplayName').disabled, true);
assert.equal(requests[1].init.method, 'PUT');
assert.equal(requests[1].init.body.get('display_name'), 'Alex <b>literal</b>');
assert.equal(requests[1].init.body.get('avatar').name, 'avatar.png');
reply(1, null, false); await failure;
assert.equal(appearance.dirty, true);
assert.equal(get('profileAvatar').src, 'blob:local-preview');
assert.equal(get('saveProfileAppearance').disabled, false);
const retry = appearance.save();
const saved = {display_name: 'Alex', avatar: 'data:image/png;base64,aGVsbG8='};
reply(2, saved); await retry;
assert.equal(get('profileAvatar').src, saved.avatar);
assert.equal(appearance.dirty, false);
assert.deepEqual(revoked, ['blob:local-preview']);
get('removeProfileAvatar').click();
assert.equal(get('profileAvatar').src, '/assets/jarvis-voice.png');
assert.equal(requests.length, 3, 'Restore default is staged until Save');
appearance.reset();
assert.equal(get('profileAvatar').src, saved.avatar, 'Cancel restores the saved image');
get('removeProfileAvatar').click();
get('profileDisplayName').value = '';
get('profileDisplayName').fire('input');
const reset = appearance.save();
assert.equal(requests[3].init.body.get('remove_avatar'), 'true');
assert.equal(requests[3].init.body.get('avatar'), null);
reply(3, {display_name:'Administrator', avatar:null}); await reset;
assert.equal(get('profileDisplayLabel').textContent, 'Administrator');
assert.equal(get('profileAvatar').src, '/assets/jarvis-voice.png');
""")


def test_late_refresh_and_cancel_do_not_replace_current_edits():
    run_browser(r"""
await load();
const refresh = appearance.load();
get('profileDisplayName').value = 'Editing now';
get('profileDisplayName').fire('input');
reply(1, {display_name:'Stale', avatar:null}); await refresh;
assert.equal(get('profileDisplayName').value, 'Editing now');
await appearance.load();
assert.equal(requests.length, 2, 'Background sync cannot reload over a dirty form');
appearance.reset();
assert.equal(get('profileDisplayName').value, 'Morgan');
const cancelled = appearance.load();
appearance.reset();
reply(2, {display_name:'Late', avatar:null}); await cancelled;
assert.equal(get('profileDisplayName').value, 'Morgan');
""")


def test_failed_load_and_invalid_upload_are_recoverable():
    run_browser(r"""
const failed = appearance.load(); reply(0, null, false); await failed;
assert.equal(get('uploadProfileAvatar').disabled, true);
assert.equal(get('retryProfileAppearance').hidden, false);
await load();
assert.equal(get('retryProfileAppearance').hidden, true);
appearance.selectFile(new File(['<svg>'], 'avatar.svg', {type:'image/svg+xml'}));
assert.equal(appearance.dirty, false);
assert.equal(appearance.file, null);
assert.equal(requests.length, 2);
assert.match(get('profileAppearanceStatus').textContent, /PNG, JPEG, or WebP/);
""")
