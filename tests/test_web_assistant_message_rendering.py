"""Exercise the real assistant-message entry point with browser I/O isolated."""

import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

HARNESS = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const effects = [], timers = [];
const escape = value => String(value).replaceAll('&', '&amp;')
  .replaceAll('<', '&lt;').replaceAll('>', '&gt;');
// Only the DOM operations used by message insertion and its disclosure buttons.
// Result selection, HTML generation, IDs and pending-tool cleanup are production code.
class Element {
  constructor() {
    this.children = []; this.dataset = {}; this.style = {}; this.events = {};
    this.className = ''; this._html = ''; this.parentElement = null;
    this.classList = {
      contains: name => this.className.split(' ').includes(name),
      add: name => { if (!this.classList.contains(name)) this.className += ' ' + name; },
      remove: name => { this.className = this.className.split(' ').filter(x => x !== name).join(' '); },
      toggle: name => this.classList.contains(name) ? this.classList.remove(name) : this.classList.add(name)
    };
  }
  set textContent(value) { this._text = value; this._html = escape(value); }
  get textContent() { return this._text || ''; }
  set innerHTML(value) {
    this._html = value; this.parts = {};
    this.headers = [...value.matchAll(/<div class="tool-card ([^"]*)">/g)].map(match => {
      const card = new Element(), header = new Element();
      card.className = 'tool-card ' + match[1]; header.parentElement = card;
      return header;
    });
    this.convertedImages = [...value.matchAll(/<div\b[^>]*data-converted-image-url="([^"]*)"/g)].map(match => {
      const image = new Element();
      image.dataset.convertedImageUrl = match[1].replace(/&(?:amp|quot|#39|lt|gt);/g,
        entity => ({'&amp;':'&', '&quot;':'"', '&#39;':"'", '&lt;':'<', '&gt;':'>'}[entity]));
      return image;
    });
    if (value.includes('class="details-toggle"')) {
      const details = new Element(), toggle = new Element();
      details.className = 'message-details collapsed'; toggle.parentElement = details;
      toggle.parts = {'.toggle-icon': new Element(), '.toggle-text': new Element()};
      this.parts['.details-toggle'] = toggle;
    }
  }
  get innerHTML() { return this._html; }
  querySelector(selector) { return this.parts?.[selector] || null; }
  querySelectorAll(selector) {
    if (selector === '.tool-card-header') return this.headers || [];
    if (selector === '.message-image.converted-file[data-converted-image-url]') return this.convertedImages || [];
    return [];
  }
  closest() { return this.parentElement; }
  addEventListener(name, handler) { this.events[name] = handler; }
  appendChild(child) { this.children.push(child); child.parentElement = this; effects.push('append'); }
  remove() {}
}
const storage = {getItem: () => null, setItem() {}, removeItem() {}};
const sandbox = {
  console, URL, Event, localStorage: storage,
  // Shipped scripts publish registry updates while their async startup settles.
  document: Object.assign(new EventTarget(), {
    createElement: () => new Element(), querySelectorAll: () => []
  }),
  window: {sessionStorage: storage, location:{origin:'https://jarvis.test'}, addEventListener() {}},
  setTimeout: fn => {timers.push(fn); return timers.length;}, clearTimeout() {},
  fetch: async () => ({ok: true, json: async () => ({tools: [], prompts: {}, workflows: {}})})
};
vm.createContext(sandbox);
const clientPath = ROOT + '/jarvis-web/client';
// Use the shipped order so a new renderer dependency must be wired in HTML too.
const html = fs.readFileSync(clientPath + '/index.html', 'utf8');
const scripts = [...html.matchAll(/<script\b[^>]*src="(\/js\/[^"?]+|\/ui-navigation\.js)"[^>]*>/g)].map(m => m[1]);
for (const path of scripts.slice(0, scripts.indexOf('/js/chat.js'))) {
  const sourcePath = path === '/ui-navigation.js' ? ROOT + '/lib/static/ui-navigation.js' : clientPath + path;
  vm.runInContext(fs.readFileSync(sourcePath, 'utf8'), sandbox, {filename: path});
}
const Utils = vm.runInContext('Utils', sandbox);
Utils.hydrateRichContent = () => effects.push('hydrate');
Utils.scrollToBottom = () => effects.push('scroll');
function loadClass(file, name, terminator) {
  const source = fs.readFileSync(clientPath + '/js/' + file, 'utf8');
  return vm.runInContext(source.slice(0, source.lastIndexOf(terminator)) + '\n' + name, sandbox);
}
const ChatUI = loadClass('chat.js', 'ChatUI', '// Create global instance');
const JarvisApp = loadClass('app.js', 'JarvisApp', '// Initialize app');
const socket = sandbox.window.jarvisSocket;
socket.conversationId = 'thread';
function chat() {
  const ui = Object.create(ChatUI.prototype);
  Object.assign(ui, {
    messagesContainer: new Element(), pendingTools: {}, pendingToolsByMessage: new Map(),
    pendingToolMessageId: null, chatOnlyEnabled: false,
    _clearMessageResponseActions: () => effects.push('clear-actions'),
    _attachCompletionGuardCard: (_el, data) => effects.push(['guard', data.completion_guard]),
    _attachMessageResponseActions: (_el, text, _data, options) => effects.push(['actions', text, options]),
    _hydrateCanvasPreview: () => effects.push('canvas-hydrate')
  });
  return ui;
}
function message(ui) { return ui.messagesContainer.children.at(-1); }
function render(ui, text, tools, payload, live = true, options = {}) {
  const data = live
    ? {message_id: 'answer', conversation_id: 'thread', data: payload}
    : {...payload, _web_message_id: 'answer'};
  ui._activatePendingToolsForMessage('answer');
  ui.addAssistantMessage(text, tools, data, options);
  return message(ui).innerHTML;
}
"""


def run_message_browser(body: str) -> None:
    script = f"const ROOT = {json.dumps(str(ROOT))};\n" + HARNESS
    script += "\n(async () => {\n" + body + "\n})().catch(error => {console.error(error); process.exit(1);});"
    result = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr


def test_shipped_command_registry_load_dispatches_document_event():
    run_message_browser(r"""
const updates = [];
sandbox.document.addEventListener('jarvis:commands-updated', event => updates.push(event));
const commands = sandbox.window.commandSystem;
await commands.refreshTools('local');
assert.equal(commands.loaded, true);
assert.equal(updates.length, 1);
assert.ok(updates[0] instanceof Event);
assert.equal(updates[0].target, sandbox.document);
""")


@pytest.mark.parametrize('live', [True, False])
def test_foreground_openclaw_result_is_visible_in_live_and_saved_tool_cards(live):
    run_message_browser(f'const live = {json.dumps(live)};\n' + r"""
const ui = chat();
const payload = {openclaw: {response: 'Sources: <A>', model: 'openclaw/main', session: 'jarvis-review'}};
const html = render(ui, 'OpenClaw replied.', ['openclaw'], payload, live);
assert.match(html, /Sources: &lt;A&gt;/);
assert.match(html, /jarvis-review/);
assert.ok(!html.includes('<pre class="tool-card-body">{}</pre>'));
""")


@pytest.mark.parametrize("live", [True, False])
@pytest.mark.parametrize("target,tag,mime", [
    ("PNG", "img", None), ("mp4", "video", "video/mp4"),
    ("ogg", "audio", "audio/ogg"), ("pdf", "a", None),
])
def test_converted_result_display_for_live_and_saved_messages(live, target, tag, mime):
    run_message_browser(f"const live = {json.dumps(live)}, target = {json.dumps(target)}, tag = {json.dumps(tag)}, mime = {json.dumps(mime)};\n" + r"""
const ui = chat();
const payload = {convert_file: {stash_ref: 'stash://space_test/f_converted',
  filename: 'Converted <example>.' + target, target_format: target, size_change: '-25%'}};
const before = JSON.stringify(payload);
const html = render(ui, 'Ready', ['convert_file'], payload, live);
assert.ok(html.includes('<' + tag));
assert.ok(html.includes('/api/stash/space_test/f_converted'));
assert.ok(html.includes('Converted &lt;example&gt;'));
assert.ok(html.includes('-25%'));
if (mime) assert.ok(html.includes('type="' + mime + '"'));
assert.equal((html.match(/class="(?:message-image|message-video|message-audio|message-file) converted-file"/g) || []).length, 1);
assert.ok(html.indexOf('converted-file') < html.indexOf('class="message-bubble"'));
assert.equal(JSON.stringify(payload), before);
assert.equal(message(ui).dataset.messageId, 'answer');
assert.equal(message(ui).dataset.conversationId, 'thread');
assert.ok(ui._renderedMessageIds.has('assistant:answer'));
assert.equal(ui.pendingToolsByMessage.has('answer'), false);
assert.deepEqual(effects.filter(x => typeof x === 'string'), ['clear-actions', 'append', 'hydrate', 'scroll']);
""")


def test_missing_invalid_or_unannounced_conversion_has_no_preview():
    run_message_browser(r"""
for (const [tools, result] of [
  [[], {stash_ref:'stash://space_test/f_file', target_format:'png'}],
  [['convert_file'], {}], [['convert_file'], {stash_ref:'invalid'}]
]) {
  const html = render(chat(), 'Ready', tools, {convert_file:result});
  assert.ok(!html.includes('converted-file'));
}
const ui = chat();
ui._activatePendingToolsForMessage('answer');
ui.pendingTools.convert_file_step2 = {toolName:'convert_file',status:'success'};
ui.addAssistantMessage('Ready', [], {message_id:'answer', data:{convert_file:{
  stash_ref:'stash://space_test/f_file',target_format:'png'
}}});
assert.ok(message(ui).innerHTML.includes('converted-file'));
""")


@pytest.mark.parametrize("live", [True, False])
def test_ocr_artifacts_keep_file_links_without_image_previews(live):
    run_message_browser(f"const live = {json.dumps(live)};\n" + r"""
for (const [action, artifactKey] of [
  ['ocr', 'markdown_stash_ref'], ['extract', 'output_stash_ref'], ['archive', 'archive_stash_ref']
]) {
  const result = {action, filename:'screenshot.jpg', document_type:'image',
    stash_ref:'stash://space_test/f_document', [artifactKey]:'stash://space_test/f_document',
    json_stash_ref:'stash://space_test/f_json'};
  const payload = {document_ocr:result}, before = JSON.stringify(payload);
  const html = render(chat(), 'Saved the document artifacts.', ['document_ocr'], payload, live);
  assert.ok(html.includes('tool-card success'));
  assert.ok(html.includes('href="/stash/view/space_test/f_document"'));
  assert.ok(html.includes('href="/stash/view/space_test/f_json"'));
  assert.ok(!html.includes('<img'), action + ' must not treat the input filename as an output image');
  assert.ok(!html.includes('showImageLightbox'));
  assert.equal(JSON.stringify(payload), before);
}
""")


@pytest.mark.parametrize("live", [True, False])
def test_stash_image_preview_uses_artifact_mime_before_filename(live):
    run_message_browser(f"const live = {json.dumps(live)};\n" + r"""
for (const [metadata, expected] of [
  [{filename:'screenshot.png'}, true],
  [{mime_type:'IMAGE/PNG'}, true],
  [{filename:'drawing', mime_type:'image/svg+xml'}, true],
  [{filename:'screenshot.jpg', mime_type:'text/plain'}, false],
  [{filename:'result.json', mime_type:'application/json'}, false],
  [{filename:'source.png', tool_origin:'web_upload', action:'analyze'}, false]
]) {
  const html = render(chat(), 'Saved.', ['stash'], {
    stash:{stash_ref:'stash://space_test/f_artifact', ...metadata}
  }, live);
  assert.equal(html.includes('<img src="/api/stash/space_test/f_artifact"'), expected,
    JSON.stringify(metadata));
  assert.equal(html.includes('showImageLightbox'), expected);
}
""")


@pytest.mark.parametrize("live", [True, False])
def test_converted_image_lightbox_uses_bound_url_data_for_live_and_saved_messages(live):
    run_message_browser(f"const live = {json.dumps(live)};\n" + r"""
const ui = chat(), opened = [];
sandbox.window.showImageLightbox = url => opened.push(url);
const html = render(ui, 'Ready', ['convert_file'], {
  convert_file: {stash_ref:"stash://Custom space/image');window.__injected=1;('.png", target_format:'png'}
}, live);
assert.ok(!html.includes('onclick='));
const images = message(ui).querySelectorAll('.message-image.converted-file[data-converted-image-url]');
assert.equal(images.length, 1);
images[0].events.click();
assert.deepEqual(opened, ["/api/stash/Custom%20space/image')%3Bwindow.__injected%3D1%3B('.png"]);
assert.equal(sandbox.window.__injected, undefined);
assert.equal(ui.pendingToolsByMessage.has('answer'), false);
""")


@pytest.mark.parametrize("live", [True, False])
def test_repeated_tool_results_keep_trace_order_and_per_message_cleanup(live):
    run_message_browser(f"const live = {json.dumps(live)};\n" + r"""
const ui = chat();
const other = {later_step1:{toolName:'later',status:'pending'}};
ui.pendingToolsByMessage.set('other-answer', other);
const html = render(ui, 'Done', ['search_web'], {
  search_web:[{title:'FIRST_SUCCESS'}, {title:'SECOND_SUCCESS'}],
  _tool_trace:[
    {tool:'search_web',ok:true,duration_ms:12},
    {tool:'search_web',ok:false,error:'MIDDLE_FAILURE'},
    {tool:'search_web',skipped:true,reason:'DO_NOT_RUN'},
    {tool:'search_web',ok:true,duration_ms:24}
  ]
}, live);
const markers = ['FIRST_SUCCESS','MIDDLE_FAILURE','DO_NOT_RUN','SECOND_SUCCESS'];
for (const marker of markers) assert.ok(html.includes(marker), marker);
for (let i=1;i<markers.length;i++) assert.ok(html.indexOf(markers[i-1]) < html.indexOf(markers[i]));
assert.equal((html.match(/class="tool-card success"/g)||[]).length,2);
assert.equal((html.match(/class="tool-card error"/g)||[]).length,1);
assert.equal((html.match(/class="tool-card skipped"/g)||[]).length,1);
assert.equal(ui.pendingToolsByMessage.get('other-answer'),other);
assert.equal(ui.pendingToolsByMessage.has('answer'),false);
const header = message(ui).querySelectorAll('.tool-card-header')[0];
header.events.click();
assert.ok(header.parentElement.classList.contains('expanded'));
""")


@pytest.mark.parametrize("family", ["amazon", "home_depot", "ebay"])
def test_product_fallback_only_runs_without_shared_renderer(family):
    run_message_browser(f"const family = {json.dumps(family)};\n" + r"""
const payloads = {
  amazon: {serpapi_search:{engine:'amazon',results:[{title:'PRODUCT <safe>',url:'https://example.test/amazon'}]}},
  home_depot: {serpapi_home_depot:{product_details:{title:'PRODUCT <safe>',url:'https://example.test/depot'}}},
  ebay: {serpapi_ebay_product:{product_summary:{title:'PRODUCT <safe>',url:'https://example.test/ebay'}}}
};
const payload = payloads[family], tools = Object.keys(payload), before = JSON.stringify(payload);
const shared = render(chat(), 'Found it', tools, payload);
assert.ok(!shared.includes('class="product-preview-card"'));
delete sandbox.window.structuredResultsRenderer;
const fallback = render(chat(), 'Found it', tools, payload, false);
assert.ok(fallback.includes('class="product-preview-card"'));
assert.ok(fallback.includes('PRODUCT &lt;safe&gt;'));
assert.equal(JSON.stringify(payload), before);
""")


def test_dedicated_media_details_and_message_hooks_keep_their_order():
    run_message_browser(r"""
const ui = chat();
const html = render(ui, 'A short answer', ['serpapi_youtube_search'], {
  raw_llm_response:'A different, much longer raw response with further context and explanation.',
  serpapi_youtube_search:{results:[{title:'VIDEO <safe>',url:'https://www.youtube.com/watch?v=dQw4w9WgXcQ'}]},
  recording:{stash_ref:'stash://space_test/f_audio', filename:'recording.ogg', mime_type:'audio/ogg'}
}, true, {allowReaction:false});
assert.equal((html.match(/class="video-embed-frame"/g)||[]).length,1);
assert.ok(html.indexOf('youtube-embed') < html.indexOf('class="message-bubble"'));
assert.ok(html.indexOf('class="message-bubble"') < html.indexOf('class="message-audio"'));
assert.ok(!html.includes('structured-results-section'));
const toggle = message(ui).querySelector('.details-toggle');
assert.ok(toggle);
let stopped = false;
toggle.events.click({stopPropagation:()=>{stopped=true;}});
assert.equal(stopped,true);
assert.equal(toggle.parentElement.classList.contains('collapsed'),false);
assert.equal(toggle.querySelector('.toggle-text').textContent,'Hide details');
const actions = effects.find(x=>Array.isArray(x)&&x[0]==='actions');
assert.equal(actions[1],'A short answer');
assert.equal(actions[2].allowReaction,false);
assert.equal(actions[2].allowCanvas,true);
timers.forEach(fn=>fn());
assert.equal(message(ui).classList.contains('new-message'),false);
""")


def test_conversation_replay_calls_real_message_renderer_and_reconciles_once():
    run_message_browser(r"""
const ui = chat();
Object.assign(ui, {
  setConversationLoading(){}, restoreRunState(){}, reconcileLiveActions(){},
  clearChat(){this.messagesContainer.children=[];this._renderedMessageIds=new Set();}
});
const app = Object.create(JarvisApp.prototype);
Object.assign(app, {chat:ui,socket,_completedResponseIds:new Set(),
  _updateActiveConversation(){},_updateConvIdBadge(){},_loadConversationHistory(){}});
const conversation = {id:'thread',reaction_message_id:'answer',messages:[{
  role:'assistant',content:'Saved result',tools_used:['convert_file'],data:{
    _web_message_id:'answer',convert_file:{stash_ref:'stash://space_test/f_saved',filename:'saved.pdf',target_format:'pdf'}
  }
}]};
await app._displayLoadedConversation(conversation);
assert.equal(ui.messagesContainer.children.length,1);
assert.ok(message(ui).innerHTML.includes('saved.pdf'));
assert.ok(message(ui).innerHTML.includes('Saved result'));
await app._displayLoadedConversation(conversation,{reconcile:true});
assert.equal(ui.messagesContainer.children.length,1);
assert.ok(app._completedResponseIds.has('answer'));
""")
