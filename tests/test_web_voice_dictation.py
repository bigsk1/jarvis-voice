"""Exercise browser dictation with real ChatUI methods and isolated audio/STT I/O."""

import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

HARNESS = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
class Element {
  constructor(tagName = 'div') {
    this.tagName = tagName.toUpperCase();
    this.children = []; this.events = {}; this.attributes = {}; this.dataset = {};
    this.style = {}; this.value = ''; this.textContent = ''; this.disabled = false;
    this.className = ''; this.isConnected = true;
    this.classList = {
      contains: name => this.className.split(' ').includes(name),
      add: (...names) => {
        this.className = [...new Set([...this.className.split(' ').filter(Boolean), ...names])].join(' ');
      },
      remove: (...names) => { this.className = this.className.split(' ').filter(x => !names.includes(x)).join(' '); },
      toggle: (name, enabled) => {
        if (enabled === undefined) enabled = !this.classList.contains(name);
        if (enabled) this.classList.add(name); else this.classList.remove(name);
      }
    };
  }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return this.attributes[name] ?? null; }
  removeAttribute(name) { delete this.attributes[name]; }
  addEventListener(name, handler) { (this.events[name] ||= []).push(handler); }
  dispatchEvent(event) {
    for (const handler of this.events[event.type] || []) handler(event);
    return true;
  }
  click() { this.dispatchEvent({type: 'click', target: this, preventDefault() {}}); }
  appendChild(child) { this.children.push(child); child.parentElement = this; return child; }
  append(...children) { children.forEach(child => this.appendChild(child)); }
  remove() {
    this.isConnected = false;
    if (this.parentElement) this.parentElement.children = this.parentElement.children.filter(child => child !== this);
  }
  querySelectorAll(selector) {
    const matches = [];
    for (const child of this.children) {
      if (selector === 'button' && child.tagName === 'BUTTON') matches.push(child);
      if (selector.startsWith('.') && child.classList?.contains(selector.slice(1))) matches.push(child);
      matches.push(...(child.querySelectorAll?.(selector) || []));
    }
    return matches;
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  focus() { this.focused = true; }
  setSelectionRange(start, end) { this.selectionStart = start; this.selectionEnd = end; }
}
const body = new Element('body');
const documentEvents = {};
const notices = [], requests = [], permissions = [], recorders = [], sent = [], authenticatedRequests = [];
const socketHandlers = {};
const socket = {
  mode: 'cloud', conversationId: 'conversation-a', connected: true,
  on: (name, handler) => { socketHandlers[name] = handler; },
  sendMessage: (...args) => { sent.push(args); return true; }
};
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return {promise, resolve, reject};
}
function stream() {
  const track = {stops: 0, stop() { this.stops += 1; }};
  return {track, getTracks: () => [track]};
}
class Recorder {
  static isTypeSupported(type) { return type === 'audio/webm;codecs=opus'; }
  constructor(stream, options = {}) {
    this.stream = stream; this.mimeType = options.mimeType; this.state = 'inactive';
    this.byteCount = 6000; recorders.push(this);
  }
  start() { this.state = 'recording'; }
  stop() {
    assert.equal(this.state, 'recording');
    this.state = 'inactive';
    // Browser stop dispatches the final audio chunk before the stop event.
    queueMicrotask(() => {
      this.ondataavailable?.({data: new Blob([new Uint8Array(this.byteCount)], {type: this.mimeType})});
      this.onstop?.();
    });
  }
}
const sandbox = {
  console: {log() {}, warn() {}, error() {}},
  Blob, FormData, AbortController, AbortSignal, Event, URL,
  MediaRecorder: Recorder,
  navigator: {mediaDevices: {getUserMedia() {
    const permission = deferred(); permissions.push(permission); return permission.promise;
  }}},
  window: {jarvisSocket: socket, addEventListener() {}},
  document: {
    body, createElement: tag => new Element(tag),
    getElementById: () => null, querySelector: () => null,
    addEventListener: (name, handler) => { (documentEvents[name] ||= []).push(handler); }
  },
  Utils: {
    toast: (...args) => notices.push(args), autoResize: field => { field.resizes = (field.resizes || 0) + 1; },
    truncate: (value, length) => value.slice(0, length)
  },
  fetch: (url, options) => {
    assert.equal(url, '/api/stt');
    const pending = deferred(); requests.push({...pending, url, options});
    // Deliberately do not reject on abort: also prove stale successful replies are ignored.
    return pending.promise;
  },
  setTimeout: (callback, delay) => setTimeout(callback, Math.min(delay, 1)), clearTimeout
};
sandbox.Utils.auth = {fetch: (...args) => { authenticatedRequests.push(args[0]); return sandbox.fetch(...args); }};
vm.createContext(sandbox);
const source = fs.readFileSync(ROOT + '/jarvis-web/client/js/chat.js', 'utf8');
const ChatUI = vm.runInContext(source.slice(0, source.lastIndexOf('// Create global instance')) + '\nChatUI;', sandbox);
const ui = Object.create(ChatUI.prototype);
Object.assign(ui, {
  inputField: new Element('textarea'), micBtn: new Element('button'),
  sendBtn: new Element('button'), stopBtn: new Element('button'),
  messagesContainer: new Element(),
  mediaRecorder: null, audioChunks: [], isRecording: false, recordingIndicator: null, _voiceSession: null,
  isProcessing: false, _conversationLoadPending: false,
  attachedDocuments: [], attachedImages: [], pendingImageFiles: [], selectedToolHints: [],
  _hasAttachedImages: () => false, _getImageAttachmentPayload: () => null,
  _validateAttachmentSelection: () => null,
  _checkAutocomplete() {}, _updateAmbientToolSuggestions() {},
  cancelAttachmentPreparation() {}, _handleImageAttachmentsForMode() {},
  clearAttachedFile() {}, clearAttachedImage() {}, _resetProcessingUi() {},
  _resetPendingToolState() {}, _resetTokenCounter() {}
});
ui._setupVoiceRecording();
ui._setupEventListeners();
ui._setupSocketListeners();
const flush = () => new Promise(resolve => setImmediate(resolve));
async function start() {
  const operation = ui._startRecording();
  const audioStream = stream();
  permissions.at(-1).resolve(audioStream);
  await operation;
  assert.equal(ui.isRecording, true);
  return audioStream;
}
async function stop() {
  const before = requests.length;
  ui._stopRecording();
  await flush();
  assert.equal(requests.length, before + 1, 'Stopping recorded speech should request transcription');
  return requests.at(-1);
}
async function respond(request, data = {ok: true, text: 'Spoken words.'}, status = 200) {
  request.resolve({ok: status >= 200 && status < 300, status, json: async () => data});
  await flush();
}
function escape() {
  for (const handler of documentEvents.keydown || []) handler({code: 'Escape', key: 'Escape', preventDefault() {}});
}
function assertDraft(value) {
  assert.equal(ui.inputField.value, value);
  assert.equal(sent.length, 0, 'Dictation must never emit a chat message');
}
function assertCancelControl() {
  assert.equal(ui.sendBtn.disabled, false, 'The existing Send button stays available as Cancel');
  assert.match(ui.sendBtn.getAttribute('aria-label') || ui.sendBtn.title || '', /cancel/i);
}
"""


def run_browser(body: str) -> None:
    script = f"const ROOT = {json.dumps(str(ROOT))};\n" + HARNESS
    script += "\n(async () => {\n" + body + "\n})().catch(error => {console.error(error); process.exit(1);});"
    result = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr


def test_transcript_preserves_current_draft_and_second_recording_appends_without_sending():
    run_browser(r"""
ui.inputField.value = 'My original draft';
const audioStream = await start();
const first = await stop();
assert.ok(audioStream.track.stops > 0, 'Release the microphone before waiting for STT');
ui.inputField.value = 'My corrected draft';
await respond(first, {ok: true, text: '  Add these words.  '});
assertDraft('My corrected draft Add these words.');
assert.ok(ui.inputField.resizes > 0);
assert.equal(ui.sendBtn.disabled, false);
assert.equal(ui.isRecording, false);
assert.equal(ui.micBtn.classList.contains('processing'), false);
await start();
await respond(await stop(), {ok: true, text: 'Continue here.'});
assertDraft('My corrected draft Add these words. Continue here.');
""")


@pytest.mark.parametrize("draft,expected", [("", "Hello."), ("A line\n", "A line\nHello.")])
def test_empty_draft_and_existing_whitespace_do_not_gain_unwanted_separators(draft, expected):
    run_browser(f"ui.inputField.value = {json.dumps(draft)};\n" + r"""
await start();
await respond(await stop(), {ok: true, text: 'Hello.'});
""" + f"assertDraft({json.dumps(expected)});")


def test_pending_permission_blocks_duplicate_recordings_and_send_and_cancel_releases_late_stream():
    run_browser(r"""
ui.inputField.value = 'Keep this draft';
const preparing = ui._startRecording();
await ui._startRecording();
assert.equal(permissions.length, 1, 'A second click cannot create a second permission request');
assertCancelControl();
ui.inputField.dispatchEvent({type: 'keydown', key: 'Enter', preventDefault() {}});
await ui.sendMessage();
assertDraft('Keep this draft');
escape();
const lateStream = stream();
permissions[0].resolve(lateStream);
await preparing;
assert.ok(lateStream.track.stops > 0);
assert.equal(recorders.length, 0, 'Cancelled permission must not start recording later');
assert.equal(ui.isRecording, false);
assert.equal(ui.sendBtn.disabled, false);
assert.equal(requests.length, 0);
assertDraft('Keep this draft');
""")


def test_existing_send_control_cancels_recording_and_preserves_editable_draft():
    run_browser(r"""
ui.inputField.value = 'Keep typed text';
const audioStream = await start();
ui.inputField.value = 'Keep edited text';
assertCancelControl();
ui.sendBtn.click();
await flush();
assertDraft('Keep edited text');
assert.equal(requests.length, 0);
assert.ok(audioStream.track.stops > 0);
assert.equal(ui.isRecording, false);
assert.equal(ui.recordingIndicator, null);
assert.equal(ui.sendBtn.disabled, false);
""")


def test_transcribing_blocks_record_and_send_and_cancelled_reply_cannot_clobber_new_recording():
    run_browser(r"""
ui.inputField.value = 'Draft';
await start();
const oldRequest = await stop();
const permissionsBefore = permissions.length;
await ui._startRecording();
assert.equal(permissions.length, permissionsBefore);
assertCancelControl();
ui.inputField.dispatchEvent({type: 'keydown', key: 'Enter', preventDefault() {}});
await ui.sendMessage();
assertDraft('Draft');
escape();
assert.ok(oldRequest.options.signal.aborted);
await start();
await respond(oldRequest, {ok: true, text: 'Obsolete words'});
assertDraft('Draft');
assert.equal(ui.isRecording, true, 'Old request cleanup must not reset the new recording');
assertCancelControl();
await respond(await stop(), {ok: true, text: 'Fresh words'});
assertDraft('Draft Fresh words');
assert.equal(ui.sendBtn.disabled, false);
""")


@pytest.mark.parametrize("failure", ["service", "transport", "empty", "short"])
def test_transcription_failures_leave_draft_and_reset_recording_controls(failure):
    run_browser(f"const failure = {json.dumps(failure)};\n" + r"""
ui.inputField.value = 'An unsent draft';
const audioStream = await start();
if (failure === 'short') {
  recorders.at(-1).byteCount = 100;
  ui._stopRecording();
  await flush();
  assert.equal(requests.length, 0);
} else {
  const request = await stop();
  if (failure === 'transport') {
    request.reject(new Error('network unavailable'));
    await flush();
  } else if (failure === 'empty') {
    await respond(request, {ok: true, text: '   '});
  } else {
    await respond(request, {ok: false, error: 'Transcription failed'}, 500);
  }
}
assertDraft('An unsent draft');
assert.equal(ui.isRecording, false);
assert.equal(ui.sendBtn.disabled, false);
assert.equal(ui.micBtn.classList.contains('processing'), false);
assert.ok(audioStream.track.stops > 0);
""")


@pytest.mark.parametrize("change", ["conversation", "mode", "loading", "clear"])
def test_late_transcription_is_discarded_when_chat_context_changes(change):
    run_browser(f"const change = {json.dumps(change)};\n" + r"""
await start();
const request = await stop();
if (change === 'conversation') socket.conversationId = 'conversation-b';
if (change === 'mode') {
  socket.mode = 'local';
  socketHandlers.modeChanged({mode: 'local'});
}
if (change === 'loading') ui.setConversationLoading(true);
if (change === 'clear') ui.clearChat();
ui.inputField.value = 'Draft in the new context';
await respond(request, {ok: true, text: 'Words from the old context'});
assertDraft('Draft in the new context');
assert.equal(ui.isRecording, false);
assert.equal(ui.micBtn.classList.contains('processing'), false);
""")


def test_denied_permission_releases_controls_and_allows_retry():
    run_browser(r"""
ui.inputField.value = 'Keep my draft';
const preparing = ui._startRecording();
permissions.at(-1).reject(Object.assign(new Error('Permission denied'), {name: 'NotAllowedError'}));
await preparing;
assertDraft('Keep my draft');
assert.equal(ui.sendBtn.disabled, false);
assert.equal(ui.isRecording, false);
assert.equal(ui.micBtn.classList.contains('preparing'), false);
assert.equal(requests.length, 0);
await start();
await respond(await stop());
assertDraft('Keep my draft Spoken words.');
""")


def test_stt_upload_uses_authenticated_route_and_recording_mode():
    run_browser(r"""
socket.mode = 'local';
await start();
const request = await stop();
assert.deepEqual(authenticatedRequests, ['/api/stt']);
assert.equal(request.options.method, 'POST');
assert.equal(request.options.body.get('mode'), 'local');
assert.equal(request.options.body.get('audio').type, 'audio/webm;codecs=opus');
assert.equal(request.options.body.get('audio').name, 'recording.webm');
assert.equal(request.options.signal.aborted, false);
await respond(request);
assertDraft('Spoken words.');
""")


def test_native_recorder_stop_enters_transcribing_state_before_reply():
    run_browser(r"""
ui.inputField.value = 'Keep my draft';
const audioStream = await start();
// A microphone track ending can stop MediaRecorder without a mic-button click.
recorders.at(-1).stop();
await flush();
assert.equal(requests.length, 1);
assert.equal(ui.isRecording, false);
assert.equal(ui.micBtn.disabled, true);
assert.equal(ui.micBtn.classList.contains('processing'), true);
assert.match(ui.micBtn.title, /transcrib/i);
assertCancelControl();
ui.micBtn.click();
assert.equal(requests.length, 1);
assert.ok(audioStream.track.stops > 0);
await respond(requests[0]);
assertDraft('Keep my draft Spoken words.');
""")


def test_recorder_error_discards_partial_audio_and_releases_microphone():
    run_browser(r"""
ui.inputField.value = 'Keep typed text';
const audioStream = await start();
recorders.at(-1).onerror({error: new Error('Device unavailable')});
await flush();
assertDraft('Keep typed text');
assert.equal(requests.length, 0);
assert.ok(audioStream.track.stops > 0);
assert.equal(ui.isRecording, false);
assert.equal(ui.micBtn.disabled, false);
assert.equal(ui.recordingIndicator, null);
assert.equal(ui.sendBtn.getAttribute('aria-label'), 'Send Message');
""")


def test_old_permission_reply_cannot_interrupt_a_new_recording():
    run_browser(r"""
ui.inputField.value = 'Draft';
const firstStart = ui._startRecording();
escape();
const newStream = await start();
const oldStream = stream();
permissions[0].resolve(oldStream);
await firstStart;
assert.ok(oldStream.track.stops > 0);
assert.equal(newStream.track.stops, 0);
assert.equal(ui.isRecording, true);
assertCancelControl();
await respond(await stop());
assertDraft('Draft Spoken words.');
""")


def test_explicit_send_after_review_uses_edited_text_exactly_once():
    run_browser(r"""
// Isolate message rendering while keeping the production Send path and socket handoff.
sandbox.window.commandSystem = {parseInput: text => ({message: text, toolHints: []})};
for (const name of ['_hideAutocomplete', '_expirePendingCompletionGuardCards', '_renderDocumentPreviews',
  'hideThinking', 'clearStatus', '_renderToolHintChips', '_hideAmbientToolSuggestions']) ui[name] = () => {};
ui.addUserMessage = () => new Element();
socket.lastRequestId = 'reviewed-message';
await start();
await respond(await stop(), {ok: true, text: 'A transcription misteak.'});
assertDraft('A transcription misteak.');
ui.inputField.value = 'A corrected message.';
assert.equal(ui.sendBtn.getAttribute('aria-label'), 'Send Message');
ui.sendBtn.click();
await flush();
assert.equal(sent.length, 1);
assert.equal(sent[0][0], 'A corrected message.');
assert.equal(ui.inputField.value, '');
assert.equal(ui.isProcessing, true);
""")


def test_mic_button_stops_into_editable_draft_and_ignores_repeated_preparing_clicks():
    run_browser(r"""
ui.micBtn.click();
ui.micBtn.click();
assert.equal(permissions.length, 1);
permissions[0].resolve(stream());
await flush();
assert.equal(ui.isRecording, true);
ui.micBtn.click();
await flush();
assert.equal(ui.isRecording, false);
assert.equal(requests.length, 1);
await respond(requests[0]);
assertDraft('Spoken words.');
assert.equal(ui.micBtn.disabled, false);
""")


@pytest.mark.parametrize("activation", ["pointer", "Space", "Enter"])
def test_cancel_activation_cannot_turn_into_send_when_transcription_finishes_mid_gesture(activation):
    run_browser(f"const activation = {json.dumps(activation)};\n" + r"""
// Keep the real Send path ready so an accidental submission is observable.
sandbox.window.commandSystem = {parseInput: text => ({message: text, toolHints: []})};
for (const name of ['_hideAutocomplete', '_expirePendingCompletionGuardCards', '_renderDocumentPreviews',
  'hideThinking', 'clearStatus', '_renderToolHintChips', '_hideAmbientToolSuggestions']) ui[name] = () => {};
ui.addUserMessage = () => new Element();
socket.lastRequestId = 'reviewed-message';
await start();
const request = await stop();
assertCancelControl();
const down = activation === 'pointer'
  ? {type: 'pointerdown', button: 0}
  : {type: 'keydown', code: activation, key: activation === 'Space' ? ' ' : 'Enter'};
ui.sendBtn.dispatchEvent({...down, preventDefault() {}});
// The request completes between pressing Cancel and releasing the pointer/key.
await respond(request, {ok: true, text: 'Unreviewed dictation.'});
assert.equal(ui.sendBtn.getAttribute('aria-label'), 'Send Message');
ui.sendBtn.dispatchEvent({type: activation === 'pointer' ? 'pointerup' : 'keyup',
  code: activation, key: activation === 'Space' ? ' ' : 'Enter', preventDefault() {}});
ui.sendBtn.click();
await flush();
assertDraft('Unreviewed dictation.');
// The completed gesture must not swallow a later intentional Send activation.
ui.inputField.value = 'Reviewed dictation.';
ui.sendBtn.click();
await flush();
assert.equal(sent.length, 1);
assert.equal(sent[0][0], 'Reviewed dictation.');
assert.equal(ui.inputField.value, '');
""")
