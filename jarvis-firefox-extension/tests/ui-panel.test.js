import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

class Element {
  constructor(tag, document) {
    this.tagName = tag; this.document = document; this.children = []; this.dataset = {}; this.attributes = {};
    this.listeners = new Map(); this.style = {}; this.value = ''; this.hidden = false; this.disabled = false;
    this.scrollHeight = 100; this.clientHeight = 100; this.scrollTop = 0;
  }
  append(...nodes) { this.children.push(...nodes.flatMap(node => node.tagName === '#fragment' ? node.children : [node])); }
  replaceChildren(...nodes) { this.children = []; this.append(...nodes); }
  set textContent(value) { this.children = []; this.text = String(value); }
  get textContent() { return (this.text || '') + this.children.map(node => node.textContent).join(''); }
  get childElementCount() { return this.children.length; }
  setAttribute(name, value) { this.attributes[name] = value; }
  getAttribute(name) { return this.attributes[name] ?? null; }
  removeAttribute(name) { delete this.attributes[name]; }
  addEventListener(name, handler) { const handlers = this.listeners.get(name) || []; handlers.push(handler); this.listeners.set(name, handlers); }
  async fire(name, data = {}) { for (const handler of this.listeners.get(name) || []) await handler({ preventDefault() {}, ...data }); }
  focus() { this.document.activeElement = this; }
  showModal() { this.open = true; }
  close() { this.open = false; void this.fire('close'); }
}

test('panel boots and supports permission-gated setup, staging, safe send and stopping', async () => {
  const html = await readFile(new URL('../ui/panel.html', import.meta.url), 'utf8');
  const elements = new Map();
  const doc = {
    activeElement: null,
    getElementById: id => elements.get(id),
    createElement: tag => new Element(tag, doc),
    createElementNS: (_namespace, tag) => new Element(tag, doc),
    createTextNode: value => { const node = new Element('#text', doc); node.textContent = value; return node; },
    createDocumentFragment: () => new Element('#fragment', doc),
  };
  for (const [, tag, attrs, id, rest] of html.matchAll(/<([a-z]+)([^>]*?)\bid="([^"]+)"([^>]*)>/g)) {
    const element = new Element(tag, doc);
    element.hidden = /\bhidden\b/.test(attrs + rest);
    elements.set(id, element);
  }
  const win = new Element('window', doc);
  const $ = id => elements.get(id);
  let state = {
    settings: { serverUrl: '', allowInsecureLocal: false }, connection: { status: 'unconfigured', error: null },
    mode: 'cloud', messages: [], conversations: [], conversationId: null,
    draft: { text: '', attachment: null, context: null }, progress: [], run: null,
  };
  const commands = [];
  const permissions = [];
  let granted = false;
  let pushState;
  let disconnect;
  const pings = [];
  const runtime = {
    connect: () => ({ postMessage: message => pings.push(message), onMessage: { addListener: listener => { pushState = listener; } }, onDisconnect: { addListener: listener => { disconnect = listener; } }, disconnect: () => disconnect() }),
    async sendMessage(message) {
      if (message.type === 'jarvis:state') return { ok: true, state: structuredClone(state) };
      commands.push(message);
      if (message.action === 'configure') state.settings = message.payload;
      if (message.action === 'connect') state.connection = { status: 'connected', authRequired: false };
      if (message.action === 'capture') state.draft.attachment = { previewUrl: 'data:image/png;base64,aGVsbG8=', width: 1920, height: 1080, source: { title: 'Error dashboard' } };
      if (message.action === 'setDraft') state.draft.text = message.payload.text;
      if (message.action === 'setMode') state.pendingMode = message.payload.mode;
      if (message.action === 'send') {
        state.messages.push({ id: 'm1', role: 'user', content: message.payload.text });
        state.draft = { text: '', attachment: null, context: null };
        state.run = { messageId: 'r1', conversationId: 'conversation-1', status: 'running' };
      }
      if (message.action === 'cancel') state.run.status = 'stopping';
      return { ok: true, state: structuredClone(state) };
    },
  };
  globalThis.document = doc;
  globalThis.window = win;
  globalThis.browser = { runtime, windows: {getCurrent: async () => ({id: 4, type: 'normal'})}, permissions: { request: async permission => { permissions.push(permission); return granted; } } };
  try {
    await import('../ui/panel.js');
    await new Promise(resolve => setImmediate(resolve));
    assert.equal($('settings-panel').hidden, false);
    assert.equal($('send-button').disabled, true);
    assert.deepEqual(pings, [{type: 'ping'}], 'Open view starts lightweight background activity');
    await $('popout-button').fire('click');
    assert.equal(commands.at(-1).action, 'openPopout');

    $('server-url').value = 'https://jarvis.example.test';
    await $('server-url').fire('input');
    await $('settings-form').fire('submit');
    assert.deepEqual(permissions[0], { origins: ['https://jarvis.example.test/*'] });
    assert.equal(commands.some(command => command.action === 'configure'), false, 'Refused server permission must prevent configure');
    granted = true;
    await $('settings-form').fire('submit');
    assert.deepEqual(commands.slice(-2).map(command => command.action), ['configure', 'connect']);
    assert.equal($('connection-label').textContent, 'Connected');

    state.conversations = [
      { id: 'recent', title: 'First from server', pinned: false },
      { id: 'pinned', title: 'Pinned project', pinned: true },
      { id: 'legacy', title: 'Legacy conversation' },
      { id: 'false-value', title: 'False string', pinned: 'false' },
    ];
    pushState({ type: 'state', state: structuredClone(state) });
    const historyItems = $('conversation-list').children;
    assert.deepEqual(historyItems.map(item => item.children[0].children[0].textContent), state.conversations.map(item => item.title), 'History preserves server order');
    const pinLabels = historyItems.map(item => item.children[0].children.find(child => child.className === 'conversation-pin'));
    assert.deepEqual(pinLabels.map(Boolean), [false, true, false, false]);
    assert.equal(pinLabels[1].textContent, 'Pinned', 'Pin status has a visible accessible label');
    assert.equal(pinLabels[1].children[0].getAttribute('aria-hidden'), 'true', 'The decorative icon does not duplicate its text label');

    $('message-input').value = 'Saved before mode change';
    await $('message-input').fire('input');
    $('mode-select').value = 'local';
    await $('mode-select').fire('change');
    assert.equal(commands.at(-1).action, 'setMode');
    assert.equal(commands.at(-1).payload.mode, 'local', 'Draft acknowledgment must not change the requested mode');
    for (const id of ['send-button', 'capture-button', 'save-settings', 'history-button', 'mode-select']) assert.equal($(id).disabled, true, `${id} waits for mode acknowledgment`);
    assert.equal($('progress-text').textContent, 'Switching to Local…');
    assert.equal($('cancel-button').hidden, true, 'Mode changes are not cancellable runs');
    state.pendingMode = null;
    state.mode = 'local';
    pushState({ type: 'state', state: structuredClone(state) });
    assert.equal($('capture-button').disabled, false);

    await $('capture-button').fire('click');
    assert.equal(commands.at(-1).payload.windowId, 4, 'Sidebar capture identifies its browser window');
    assert.equal($('attachment-panel').hidden, false);
    assert.equal($('attachment-title').textContent, 'Error dashboard');
    assert.equal($('send-button').disabled, false, 'A staged screenshot can be sent without typed text');

    $('message-input').value = 'Why did this fail?';
    await $('message-input').fire('input');
    pushState({ type: 'state', state: structuredClone(state) });
    assert.equal($('message-input').value, 'Why did this fail?', 'Unrelated state must preserve local typing');
    await $('composer-form').fire('submit');
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(commands.find(command => command.action === 'send').payload.text, 'Why did this fail?');
    assert.equal($('message-input').value, '');
    assert.equal($('attachment-panel').hidden, true);
    assert.equal($('send-button').disabled, true);
    assert.equal($('cancel-button').disabled, false);

    disconnect();
    assert.equal($('cancel-button').disabled, true, 'Stop must wait for a restored background bridge');
    assert.equal($('send-button').disabled, true);
    pushState({ type: 'state', state: structuredClone(state) });
    assert.equal($('cancel-button').disabled, false, 'Confirmed run state enables Stop again');

    await $('cancel-button').fire('click');
    await new Promise(resolve => setImmediate(resolve));
    assert.equal($('cancel-button').disabled, true);
    assert.equal($('cancel-button').textContent, 'Stopping…');
    state.connection.status = 'disconnected';
    pushState({ type: 'state', state: structuredClone(state) });
    assert.equal($('save-settings').disabled, true, 'Changing server remains blocked during an accepted request');
    assert.equal($('reconnect-button').hidden, false);
    assert.equal($('reconnect-button').disabled, false, 'An accepted request must not block reconnecting');
    await $('reconnect-button').fire('click');
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(commands.at(-1).action, 'connect');
    state.connection.status = 'recovering';
    state.run = null;
    pushState({ type: 'state', state: structuredClone(state) });
    assert.equal($('send-button').disabled, true);
    assert.equal($('progress-area').hidden, false);
  } finally {
    await win.fire('pagehide');
    delete globalThis.document;
    delete globalThis.window;
    delete globalThis.browser;
  }
});
