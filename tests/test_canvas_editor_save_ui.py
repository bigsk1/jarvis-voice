"""Run the actual Canvas editor handlers against controlled HTTP responses."""

import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("scenario", ["url", "shrink", "server", "html", "network", "success"])
def test_editor_only_closes_after_a_confirmed_save(scenario):
    script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(ROOT + '/jarvis-canvas/client/static/js/canvas.js', 'utf8');
const notices = [], requests = [], selected = [];
let refreshed = 0;
const modal = new Set(['active']);
const elements = {
  editTitle: {value: 'Draft title'},
  editTags: {value: 'report, test'},
  editContent: {value: 'Unsaved draft'},
  editModal: {classList: {remove: value => modal.delete(value)}}
};
const errors = {
  url: [400, 'Page content contains a truncated URL'],
  shrink: [409, 'Content replacement would remove most of the existing page'],
  server: [500, 'Could not save page']
};
const sandbox = {
  document: {getElementById: id => elements[id]},
  showToast: (...args) => notices.push(args),
  fetchPages: async () => {
    await new Promise(resolve => setImmediate(resolve));
    refreshed++;
  },
  selectPage: id => {
    assert.equal(refreshed, 1, 'Page selection must follow the completed list refresh');
    selected.push(id);
  },
  fetch: async (url, options) => {
    requests.push({url, options});
    if (SCENARIO === 'network') throw new Error('Failed to fetch');
    const [status, error] = errors[SCENARIO] || [SCENARIO === 'html' ? 502 : 200, null];
    return {
      ok: status === 200, status,
      headers: {get: () => SCENARIO === 'html' ? 'text/html' : 'application/json'},
      json: async () => ({error})
    };
  }
};
vm.createContext(sandbox);
vm.runInContext('let editingPage = "page_original"; let currentPage = "page_original";', sandbox);
for (const [start, end] of [
  ['async function saveEdit()', '// Print function'],
  ['async function parseApiResponse(', 'async function loadXaiPdfShareStatus('],
  ['function closeEditModal()', '// Search']
]) {
  const begin = source.indexOf(start);
  assert.ok(begin >= 0);
  vm.runInContext(source.slice(begin, source.indexOf(end, begin)), sandbox);
}
(async () => {
  await sandbox.saveEdit();
  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, '/api/pages/page_original');
  assert.equal(requests[0].options.method, 'PUT');
  assert.deepEqual(JSON.parse(requests[0].options.body), {
    title: 'Draft title', tags: ['report', 'test'], content: 'Unsaved draft'
  });
  if (SCENARIO === 'success') {
    assert.deepEqual(notices, [['Page updated', 'success']]);
    assert.equal(modal.has('active'), false);
    assert.equal(vm.runInContext('editingPage', sandbox), null);
    assert.equal(refreshed, 1);
    assert.deepEqual(selected, ['page_original']);
  } else {
    assert.equal(notices.length, 1);
    assert.equal(notices[0][1], 'error');
    if (errors[SCENARIO]) assert.equal(notices[0][0], errors[SCENARIO][1]);
    if (SCENARIO === 'html') assert.match(notices[0][0], /502/);
    assert.equal(modal.has('active'), true);
    assert.equal(elements.editContent.value, 'Unsaved draft');
    assert.equal(vm.runInContext('editingPage', sandbox), 'page_original');
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
