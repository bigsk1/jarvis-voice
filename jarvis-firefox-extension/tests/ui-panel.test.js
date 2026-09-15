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
    hidden: false,
    focused: true,
    listeners: new Map(),
    hasFocus() { return this.focused; },
    addEventListener(name, handler) { this.listeners.set(name, handler); },
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
  let notificationPermission = false;
  let draftReplyGate = null;
  let pushState;
  let disconnect;
  const pings = [];
  const runtime = {
    connect: () => ({ postMessage: message => pings.push(message), onMessage: { addListener: listener => { pushState = listener; } }, onDisconnect: { addListener: listener => { disconnect = listener; } }, disconnect: () => disconnect() }),
    async sendMessage(message) {
      if (message.type === 'jarvis:state') return { ok: true, state: structuredClone(state) };
      commands.push(message);
      if (message.action === 'configure') state.settings = message.payload;
      if (message.action === 'updatePreferences') state.settings.preferences = {
        showBadge: true, desktopNotifications: false, notificationPreview: false,
        ...state.settings.preferences, ...message.payload,
      };
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
      const response = { ok: true, state: structuredClone(state) };
      if (message.action === 'setDraft' && draftReplyGate) {
        const waiting = draftReplyGate;
        draftReplyGate = null;
        await waiting;
      }
      return response;
    },
  };
  globalThis.document = doc;
  globalThis.window = win;
  globalThis.browser = { runtime, windows: {getCurrent: async () => ({id: 4, type: 'normal'})}, permissions: { request: async permission => {
    permissions.push(permission);
    return permission.permissions ? notificationPermission : granted;
  } } };
  try {
    await import('../ui/panel.js');
    await new Promise(resolve => setImmediate(resolve));
    assert.equal($('settings-panel').hidden, false);
    assert.equal($('send-button').disabled, true);
    assert.deepEqual(pings, [{type: 'ping'}, {type: 'viewStatus', visible: true, conversationId: null}], 'Open view reports visibility once alongside lightweight background activity');
    assert.equal($('show-badge').checked, true);
    assert.equal($('desktop-notifications').checked, false);
    assert.equal($('notification-preview').checked, false);
    assert.equal($('notification-preview').disabled, true);
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

    const configurationCommands = commands.filter(command => ['configure', 'connect'].includes(command.action)).length;
    $('desktop-notifications').checked = true;
    await $('desktop-notifications').fire('change');
    assert.deepEqual(permissions.at(-1), {permissions: ['notifications']});
    assert.equal($('desktop-notifications').checked, false, 'Denied permission restores the unchecked setting');
    assert.match($('notification-help').textContent, /not allowed/);
    assert.equal(commands.some(command => command.action === 'updatePreferences'), false, 'No preference is enabled after permission denial');
    notificationPermission = true;
    $('desktop-notifications').checked = true;
    const enableNotifications = $('desktop-notifications').fire('change');
    assert.deepEqual(permissions.at(-1), {permissions: ['notifications']}, 'Permission request starts inside the checkbox user gesture');
    assert.equal($('desktop-notifications').disabled, true);
    pushState({ type: 'state', state: structuredClone(state) });
    assert.equal($('desktop-notifications').checked, true, 'Progress updates do not overwrite a permission decision in flight');
    await enableNotifications;
    assert.deepEqual(commands.at(-1), {type: 'jarvis:command', action: 'updatePreferences', payload: {desktopNotifications: true}});
    assert.equal($('notification-preview').disabled, false);
    $('notification-preview').checked = true;
    await $('notification-preview').fire('change');
    assert.deepEqual(commands.at(-1).payload, {notificationPreview: true});
    const permissionCount = permissions.length;
    $('show-badge').checked = false;
    await $('show-badge').fire('change');
    assert.deepEqual(commands.at(-1).payload, {showBadge: false});
    assert.equal(permissions.length, permissionCount, 'Badge and preview preferences need no additional permission request');
    assert.equal(commands.filter(command => ['configure', 'connect'].includes(command.action)).length, configurationCommands, 'Preference changes do not reconnect Jarvis');
    state.settings.preferences.desktopNotifications = false;
    pushState({ type: 'state', state: structuredClone(state) });
    assert.equal($('desktop-notifications').checked, false, 'Background permission removal is reflected in Settings');
    assert.equal($('notification-preview').disabled, true);

    const viewMessages = () => pings.filter(message => message.type === 'viewStatus');
    const initialViewMessages = viewMessages().length;
    pushState({ type: 'state', state: structuredClone(state) });
    pushState({ type: 'state', state: structuredClone(state) });
    assert.equal(viewMessages().length, initialViewMessages, 'State broadcasts cannot create a view-status feedback loop');
    doc.focused = false;
    await win.fire('blur');
    assert.deepEqual(viewMessages().at(-1), {type: 'viewStatus', visible: false, conversationId: null});
    doc.focused = true;
    await win.fire('focus');
    assert.equal(viewMessages().at(-1).visible, true);
    doc.hidden = true;
    doc.listeners.get('visibilitychange')();
    assert.equal(viewMessages().at(-1).visible, false, 'A focused but hidden view is not being read');
    doc.hidden = false;
    doc.listeners.get('visibilitychange')();
    state.conversationId = 'read-conversation';
    pushState({ type: 'state', state: structuredClone(state) });
    assert.deepEqual(viewMessages().at(-1), {type: 'viewStatus', visible: true, conversationId: 'read-conversation'});

    const imageUrl = 'https://images.example.test/picture.png?value=%3Cimg%3E';
    state.draft = {text: `Analyze this image: ${imageUrl}`, attachment: null, context: {kind: 'image', url: imageUrl, title: '<img src=x>', text: 'Default image question'}};
    pushState({ type: 'state', state: structuredClone(state) });
    assert.equal($('context-title').textContent, 'Image URL');
    assert.equal($('context-text').textContent, imageUrl);
    assert.equal($('context-hint').hidden, false);
    assert.equal($('attachment-panel').hidden, true, 'An image URL is not fetched for a preview');
    assert.equal($('message-input').placeholder, 'Ask about this image…');
    $('message-input').value = `/research ${imageUrl}`;
    await $('message-input').fire('input');
    assert.equal($('context-hint').hidden, true, 'A slash command does not advertise an automatic image-analysis hint');
    $('message-input').value = 'A different question';
    await $('message-input').fire('input');
    assert.equal($('context-hint').hidden, true, 'Editing out the URL removes the image-analysis hint immediately');
    state.draft = {text: '', attachment: null, context: null};

    // Let a pre-staging edit reach the background, but hold its acknowledgment.
    let releaseDraftReply;
    draftReplyGate = new Promise(resolve => { releaseDraftReply = resolve; });
    await new Promise(resolve => setTimeout(resolve, 280));
    assert.equal(commands.at(-1).action, 'setDraft');
    assert.equal(commands.at(-1).payload.imageStageId, null);
    $('message-input').value = 'Keep this newer local question';
    await $('message-input').fire('input');
    state.draft = {
      text: `Older saved question\n\nAnalyze this image:\n${imageUrl}`,
      attachment: null,
      context: {kind: 'image', stageId: 'image-stage-new', url: imageUrl, title: 'Image'},
    };
    pushState({type: 'state', state: structuredClone(state)});
    const mergedText = `Keep this newer local question\n\nAnalyze this image:\n${imageUrl}`;
    assert.equal($('message-input').value, mergedText, 'A new image stage merges with dirty local text');
    assert.equal($('context-hint').hidden, false);
    releaseDraftReply();
    await new Promise(resolve => setImmediate(resolve));
    assert.equal($('context-panel').hidden, false, 'A late pre-staging acknowledgment cannot erase the new image');
    assert.equal($('message-input').value, mergedText);
    await new Promise(resolve => setTimeout(resolve, 280));
    assert.deepEqual(commands.at(-1).payload, {text: mergedText, imageStageId: 'image-stage-new'});
    pushState({type: 'state', state: structuredClone(state)});
    assert.equal($('message-input').value, mergedText, 'Repeated state broadcasts do not duplicate the image URL');
    $('message-input').value = 'Continue without the image';
    await $('message-input').fire('input');
    await new Promise(resolve => setTimeout(resolve, 280));
    assert.deepEqual(commands.at(-1).payload, {text: 'Continue without the image', imageStageId: 'image-stage-new'},
      'Intentional removal is tagged with the stage the user actually saw');
    state.draft.context = null;
    pushState({type: 'state', state: structuredClone(state)});
    assert.equal($('context-panel').hidden, true);

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
