"""Exercise Canvas import handlers without the removed replace/import toggle."""

import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("scenario", ["open", "success", "delayed_refresh", "rejection"])
def test_import_modal_and_submission_without_replace_toggle(scenario):
    script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(ROOT + '/jarvis-canvas/client/static/js/canvas.js', 'utf8');
const template = fs.readFileSync(ROOT + '/jarvis-canvas/client/templates/canvas.html', 'utf8');
const notices = [], requests = [], selected = [];
let refreshed = 0;
let finishRefresh;
const refreshComplete = new Promise(resolve => {finishRefresh = resolve;});
const succeeds = SCENARIO === 'success' || SCENARIO === 'delayed_refresh';
const modal = new Set(['active']), preview = new Set(['active']);
const elements = {
  uploadFile: {value: 'old.json'},
  uploadSubmitBtn: {disabled: false},
  uploadPreview: {classList: {remove: value => preview.delete(value)}},
  uploadModal: {classList: {
    add: value => modal.add(value), remove: value => modal.delete(value)
  }}
};
const sandbox = {
  document: {getElementById: id => elements[id]},
  showToast: (...args) => notices.push(args),
  fetchPages: () => {
    refreshed++;
    return SCENARIO === 'delayed_refresh' ? refreshComplete : Promise.resolve();
  },
  selectPage: id => selected.push(id),
  fetch: async (url, options) => {
    requests.push({url, options});
    return {
      ok: succeeds,
      json: async () => succeeds
        ? {action: 'created', page: {id: 'page_fresh'}}
        : {error: 'Page content contains a truncated URL'}
    };
  }
};
vm.createContext(sandbox);
const begin = source.indexOf('// Upload modal functions');
const end = source.indexOf('// Drag and drop support for upload', begin);
assert.ok(begin >= 0 && end > begin);
vm.runInContext(source.slice(begin, end), sandbox);
const incoming = {id: 'page_existing', title: 'Imported', content: 'Draft content'};
vm.runInContext('uploadData = ' + JSON.stringify(incoming), sandbox);
(async () => {
  if (SCENARIO === 'open') {
    sandbox.openUploadModal();
    assert.equal(vm.runInContext('uploadData', sandbox), null);
    assert.equal(elements.uploadFile.value, '');
    assert.equal(elements.uploadSubmitBtn.disabled, true);
    assert.equal(preview.has('active'), false);
    assert.equal(modal.has('active'), true);
    assert.equal(template.includes('uploadForceNew'), false);
    assert.match(template, /Imports create a new page\./);
    assert.equal(requests.length, 0);
    return;
  }
  const submission = sandbox.submitUpload();
  if (SCENARIO === 'delayed_refresh') {
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(refreshed, 1);
    assert.deepEqual(selected, [], 'The new page cannot render before its row is loaded');
    finishRefresh();
  }
  await submission;
  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, '/api/pages/upload');
  assert.equal(requests[0].options.method, 'POST');
  assert.deepEqual(JSON.parse(requests[0].options.body), incoming);
  if (succeeds) {
    assert.deepEqual(notices, [['Page created!', 'success']]);
    assert.equal(modal.has('active'), false);
    assert.equal(vm.runInContext('uploadData', sandbox), null);
    assert.equal(refreshed, 1);
    assert.deepEqual(selected, ['page_fresh']);
  } else {
    assert.deepEqual(notices, [['Page content contains a truncated URL', 'error']]);
    assert.equal(modal.has('active'), true);
    assert.deepEqual(JSON.parse(vm.runInContext('JSON.stringify(uploadData)', sandbox)), incoming);
    assert.equal(refreshed, 0);
    assert.deepEqual(selected, []);
  }
})().catch(error => {console.error(error); process.exit(1);});
"""
    subprocess.run(
        ["node", "-e", f"const ROOT = {json.dumps(str(ROOT))}; const SCENARIO = {json.dumps(scenario)};\n{script}"],
        check=True,
        timeout=15,
        cwd=ROOT,
    )
