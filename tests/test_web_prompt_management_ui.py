"""Classic-script Prompt Library UI contracts."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_prompt_settings_markup_and_script_order_are_present():
    html = (ROOT / "jarvis-web/client/index.html").read_text()

    assert 'data-settings-tab="tools">Tools</button>' in html
    assert 'data-settings-tab="prompts">Prompts</button>' in html
    assert html.index('data-settings-tab="tools"') < html.index('data-settings-tab="prompts"')
    assert 'id="settings-prompts"' in html
    assert 'id="prompt-preview-mode"' in html
    assert 'id="promptContent"' in html
    assert html.index('/js/prompt-library.js') < html.index('/js/app.js')


def test_settings_lifecycle_hides_global_save_and_guards_dirty_prompt_drafts():
    source = (ROOT / "jarvis-web/client/js/app.js").read_text()

    assert "['profile', 'integrations', 'prompts'].includes(tabName)" in source
    assert "activeTab === 'prompts'" in source
    assert "!this.promptLibrary.confirmDiscard()" in source
    assert "this._closeSettingsModal();" in source


def test_prompt_editor_parses_hints_and_enforces_client_name_contract():
    script = r"""
const fs = require('fs');
global.window = {};
const source = fs.readFileSync('jarvis-web/client/js/prompt-library.js', 'utf8');
eval(source + '\nglobal.PromptLibrary = PromptLibrary;');

const editor = Object.create(global.PromptLibrary.prototype);
editor.nameInput = {value: 'evidence_first'};
editor.contentInput = {value: `---
tool_hints:
  - search_docs
  - search_web
---

# Evidence First

Use available evidence.`};
const parsed = editor.parseDraft(editor.contentInput.value);
if (parsed.title !== 'Evidence First') throw new Error(`title: ${parsed.title}`);
if (parsed.hints.join(',') !== 'search_docs,search_web') throw new Error(`hints: ${parsed.hints}`);
if (editor.clientErrors().length !== 0) throw new Error(editor.clientErrors().join('; '));

editor.nameInput.value = 'Not Valid';
if (!editor.clientErrors().some(message => message.includes('lowercase'))) {
  throw new Error('invalid name was accepted');
}
"""
    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)


def test_prompt_save_uses_management_api_and_refreshes_existing_registry():
    script = r"""
const assert = require('node:assert/strict');
const fs = require('fs');
global.window = {};
global.Utils = {toast() {}};
const source = fs.readFileSync('jarvis-web/client/js/prompt-library.js', 'utf8');
eval(source + '\nglobal.PromptLibrary = PromptLibrary;');

(async () => {
  const requests = [];
  global.fetch = async (url, options) => {
    requests.push({url, options});
    return {ok: true, json: async () => ({ok: true, message: 'Saved @new_prompt'})};
  };
  let refreshedMode = null;
  window.commandSystem = {refreshTools: async mode => { refreshedMode = mode; }};
  const editor = Object.create(global.PromptLibrary.prototype);
  Object.assign(editor, {
    editorMode: 'new', currentRecord: null,
    nameInput: {value: 'new_prompt'},
    contentInput: {value: '# New Prompt\n'},
    modeSelect: {value: 'local'},
    saveButton: {disabled: false},
    clientErrors: () => [],
    captureDraft: () => ({name: 'new_prompt', content: '# New Prompt\n'}),
    load: async () => {}, select: () => {}, activeMode: () => 'cloud',
    renderValidation: errors => { throw new Error(errors.join('; ')); }
  });

  await editor.save();
  assert.equal(requests[0].url, '/api/prompts/personal?mode=local');
  assert.equal(requests[0].options.method, 'POST');
  assert.equal(JSON.parse(requests[0].options.body).override_shared, false);
  assert.equal(refreshedMode, 'cloud');
  assert.equal(editor.saveButton.disabled, false);
})().catch(error => { console.error(error); process.exit(1); });
"""
    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)


def test_prompt_mode_preview_preserves_dirty_draft_without_discard_gate():
    source = (ROOT / "jarvis-web/client/js/prompt-library.js").read_text()
    listener = source[source.index("this.modeSelect?.addEventListener('change'") :]
    listener = listener[: listener.index("  }")]

    assert "captureDraft()" in listener
    assert "preserveDraft: draft" in listener
    assert "confirmDiscard" not in listener


def test_duplicate_copies_dirty_draft_without_discarding_and_stays_dirty():
    script = r"""
const assert = require('node:assert/strict');
const fs = require('fs');
let confirmations = 0;
global.window = {confirm: () => { confirmations += 1; return true; }};
const source = fs.readFileSync('jarvis-web/client/js/prompt-library.js', 'utf8');
eval(source + '\nglobal.PromptLibrary = PromptLibrary;');

const editor = Object.create(global.PromptLibrary.prototype);
Object.assign(editor, {
  records: [], editorMode: 'edit',
  currentRecord: {name: 'evidence_first', source: 'personal'},
  nameInput: {value: 'evidence_first', disabled: true, focus() {}, select() {}},
  contentInput: {value: '# Edited draft\n\nKeep these unsaved changes.'},
  saveButton: {}, restoreButton: {}, deleteButton: {}, duplicateButton: {},
  cleanSnapshot: {
    name: 'evidence_first', content: '# Original',
    editorMode: 'edit', originName: 'evidence_first'
  },
  updateDraftPreview() {}
});

editor.duplicate();
assert.equal(confirmations, 0);
assert.equal(editor.editorMode, 'new');
assert.equal(editor.currentRecord, null);
assert.equal(editor.nameInput.value, 'evidence_first_copy');
assert.equal(editor.contentInput.value, '# Edited draft\n\nKeep these unsaved changes.');
assert.equal(editor.isDirty(), true);
"""
    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)


def test_draft_tool_hint_diagnostics_refresh_while_typing():
    script = r"""
const assert = require('node:assert/strict');
const fs = require('fs');
global.window = {};
class FakeElement {
  constructor() { this.children = []; this.textContent = ''; this.className = ''; }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this.children = [...items]; }
}
global.document = {createElement: () => new FakeElement()};
const source = fs.readFileSync('jarvis-web/client/js/prompt-library.js', 'utf8');
eval(source + '\nglobal.PromptLibrary = PromptLibrary;');

const preview = new FakeElement();
const validation = new FakeElement();
const editor = Object.create(global.PromptLibrary.prototype);
Object.assign(editor, {
  editorMode: 'edit',
  currentRecord: {
    name: 'live_status', source: 'personal', overrides_shared: false,
    content: '# Previously saved', availability_status: 'available', warnings: []
  },
  nameInput: {value: 'live_status'},
  contentInput: {value: `---
tool_hints:
  - missing_tool
---
# Live status`},
  tools: [{name: 'active_tool', enabled: true, available: true, blocked: false}],
  context: {mode: 'local', tool_profile: 'offline'},
  preview, validation
});
const availability = () => preview.children
  .find(item => item.children?.[0]?.textContent === 'Availability')
  .children[1].textContent;

editor.updateDraftPreview();
assert.equal(availability(), 'Not in current @ menu');
assert.ok(preview.children.some(item => item.textContent.includes('not in the current tool registry')));
assert.ok(validation.children.some(item => item.textContent.includes('#missing_tool')));

editor.toolSelect = {value: 'missing_tool'};
editor.addSelectedTool();
assert.ok(validation.children.some(item => item.textContent.includes('already in tool_hints')));
assert.ok(validation.children.some(item => item.textContent.includes('not in the current tool registry')));

editor.contentInput.value = `---
tool_hints: [active_tool, missing_tool]
---
# Live status`;
editor.updateDraftPreview();
assert.equal(availability(), 'Available with reduced hints');
assert.ok(validation.children.some(item => item.textContent.includes('Multiple hints')));
"""
    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)


def test_saved_prompt_wrapper_is_guidance_and_names_user_precedence():
    source = (ROOT / "jarvis-web/server/sockets/chat.py").read_text()

    assert "[CONTEXT - Saved prompt @{safe_prompt_name}]" in source
    assert "These are reusable guidelines for the user's request, not a separate task." in source
    assert "The user's explicit request and constraints take" in source
    assert "treat current tool schemas and returned data as" in source
    assert "[END SAVED PROMPT]" in source
