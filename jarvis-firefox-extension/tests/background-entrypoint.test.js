import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
import { captureSource as captureActual } from '../browser/capture.js';
import { normalizeSource, resolveCurrentSource } from '../browser/source.js';
import { setupMenus, MENU_IDS } from '../browser/menus.js';

const PANEL = 'moz-extension://companion-test/ui/panel.html';
const EXTENSION_ID = 'jarvis-companion@test';
const ownSender = { id: EXTENSION_ID, url: PANEL };
const tick = () => new Promise(resolve => setImmediate(resolve));

function event() {
  const listeners = [];
  return {
    listeners,
    addListener(listener) { listeners.push(listener); },
    removeListener(listener) { const index = listeners.indexOf(listener); if (index >= 0) listeners.splice(index, 1); },
    async fire(...args) { let result; for (const listener of listeners) result = await listener(...args); return result; },
  };
}

async function boot({ deferRestore = false, deferCapture = false } = {}) {
  const calls = { captures: [], creates: [], updates: [], stages: [], checkpoints: 0, sends: 0, uploads: 0, connects: 0, closes: 0, network: 0 };
  const sourceTab = { id: 17, windowId: 4, active: true, url: 'https://example.test/dashboard', title: 'Source dashboard' };
  const normalTabs = new Map([[sourceTab.id, sourceTab]]);
  let releaseCapture;
  const captureGate = new Promise(resolve => { releaseCapture = resolve; });
  const browser = {
    runtime: { id: EXTENSION_ID, getURL: path => `moz-extension://companion-test/${path}`, onConnect: event(), onMessage: event(), onStartup: event(), onInstalled: event() },
    action: { onClicked: event() },
    sidebarAction: {open: async () => calls.creates.push({type: 'sidebar'})},
    storage: {session: {get: async () => ({}), set: async () => {}}},
    permissions: { onRemoved: event(), contains: async () => true },
    menus: { onClicked: event(), removeAll: async () => {}, create: details => calls.creates.push(details) },
    windows: {
      onFocusChanged: event(),
      getAll: async () => [{id: 4, type: 'normal'}],
      get: async id => ({ id, type: id === 4 ? 'normal' : 'popup', incognito: false }),
      getLastFocused: async () => ({id: 4, type: 'normal'}),
      create: async options => { calls.creates.push(options); return { id: 90 }; },
      update: async (...args) => calls.updates.push(args),
    },
    tabs: {
      get: async id => { if (!normalTabs.has(id)) throw new Error('Tab closed'); return normalTabs.get(id); },
      query: async ({windowId}) => [...normalTabs.values()].filter(tab => tab.windowId === windowId && tab.active),
      captureVisibleTab: async (windowId, options) => { calls.captures.push({ windowId, options }); if (deferCapture) await captureGate; return 'data:image/png;base64,c291cmNl'; },
    },
  };
  let restored;
  const restoring = new Promise(resolve => { restored = resolve; });
  let client;
  class Client {
    constructor(options) {
      client = this;
      this.options = options;
      this.state = { settings: {}, connection: { status: 'connected' }, source: null, draft: { text: '', attachment: null, context: null }, messages: [], conversations: [], run: null };
      this.intent = true;
      this.transport = { socket: { connected: true }, close: () => { calls.closes += 1; }, upload: () => { calls.uploads += 1; } };
    }
    restore() { return restoring; }
    requireIdle() { if (this.state.run?.status === 'running') throw new Error('A request is active'); }
    async checkpoint() { calls.checkpoints += 1; }
    publish() { this.options.onState(this.state); }
    changed() { this.publish(); }
    async stage(value) { calls.stages.push(value); this.state.source = value.source; this.state.draft.attachment = value.attachment || null; this.state.draft.context = value.context || null; this.publish(); }
    async setDraft(text) { this.state.draft.text = text; this.publish(); }
    async configure(settings) { this.state.settings = settings; this.state.draft = {text: '', attachment: null, context: null}; }
    async connect() { calls.connects += 1; }
    async send() { calls.sends += 1; }
    async logout() { calls.closes += 1; this.transport = null; }
  }
  const captureSource = (api, source) => captureActual(api, source, {
    decodeImage: async () => ({ width: 1920, height: 1080 }),
    createCanvas: () => ({ getContext: () => ({ fillRect() {}, drawImage() {} }), toDataURL: () => 'data:image/jpeg;base64,c291cmNl' }),
    now: () => '2026-09-14T00:00:00.000Z',
  });
  const sandbox = { browser, JarvisClient: Client, captureSource, normalizeSource, resolveCurrentSource, setupMenus, URL, console, setTimeout, clearTimeout, fetch: () => { calls.network += 1; throw new Error('Unexpected network request'); } };
  const context = vm.createContext(sandbox);
  const vendor = await readFile(new URL('../vendor/socket.io.min.js', import.meta.url), 'utf8');
  // Execute the actual browser distribution with undefined top-level `this`,
  // as in an ES module. It must expose globalThis.io without CommonJS globals.
  new vm.Script(`(function () { 'use strict';\n${vendor}\n}).call(undefined);`).runInContext(context);
  const original = await readFile(new URL('../background.js', import.meta.url), 'utf8');
  const source = original.replace(/^import [^\n]*\n/gm, '');
  new vm.Script(source, { filename: 'background.js' }).runInContext(context);
  if (!deferRestore) restored();
  await tick();
  return { browser, calls, client, sourceTab, normalTabs, restored, context, releaseCapture };
}

function viewPort(sender = ownSender, name = 'jarvis-ui') {
  return {
    sender, name, messages: [], disconnected: false, onDisconnect: event(), onMessage: event(),
    postMessage(message) { this.messages.push(message); },
    disconnect() { this.disconnected = true; void this.onDisconnect.fire(); },
  };
}

test('background starts with bundled Socket.IO and registers wake handlers before restoring state', async () => {
  const app = await boot({ deferRestore: true });
  assert.equal(typeof app.client.options.ioFactory, 'function');
  for (const api of [app.browser.runtime.onMessage, app.browser.runtime.onConnect, app.browser.action.onClicked, app.browser.menus.onClicked, app.browser.runtime.onInstalled, app.browser.runtime.onStartup, app.browser.permissions.onRemoved, app.browser.windows.onFocusChanged]) assert.equal(api.listeners.length, 1);
  const pending = app.browser.runtime.onMessage.fire({ type: 'jarvis:state' }, ownSender);
  app.restored();
  assert.equal((await pending).ok, true);
  assert.equal(app.calls.network, 0);
});

test('only this extension panel can fetch state, issue commands or hold a UI port', async () => {
  const app = await boot();
  assert.equal(new URL(PANEL).origin, 'null', 'Exercise the opaque moz-extension origin regression');
  const valid = await app.browser.runtime.onMessage.fire({ type: 'jarvis:command', action: 'setDraft', payload: { text: 'Hello' } }, ownSender);
  assert.equal(valid.ok, true);
  assert.equal(app.client.state.draft.text, 'Hello');
  const disallowed = [
    { id: EXTENSION_ID, url: 'https://example.test/ui/panel.html' },
    { id: EXTENSION_ID, url: 'moz-extension://different-extension/ui/panel.html' },
    { id: EXTENSION_ID, url: 'moz-extension://companion-test/background.html' },
    { id: 'other-extension', url: PANEL },
    { ...ownSender, tab: { incognito: true } },
    { id: EXTENSION_ID },
  ];
  for (const sender of disallowed) {
    const response = await app.browser.runtime.onMessage.fire({ type: 'jarvis:command', action: 'send', payload: { text: 'Not allowed' } }, sender);
    assert.equal(response.ok, false);
    const port = viewPort(sender);
    await app.browser.runtime.onConnect.fire(port);
    assert.equal(port.disconnected, true);
  }
  assert.equal(app.calls.sends, 0);
});

test('closing the pop-out detaches its view while accepted background chat remains running', async () => {
  const app = await boot();
  app.client.state.run = { status: 'running', requestId: 'r1' };
  const socket = app.client.transport;
  const port = viewPort();
  await app.browser.runtime.onConnect.fire(port);
  await tick();
  assert.equal(port.messages.length, 1);
  port.disconnect();
  const before = port.messages.length;
  app.client.changed();
  assert.equal(port.messages.length, before, 'Closed UI receives no more state updates');
  assert.equal(app.client.transport, socket);
  assert.equal(app.client.state.run.status, 'running');
  assert.equal(app.calls.closes, 0);
});

test('toolbar selects its browser source and capture stages that window without uploading or sending', async () => {
  const app = await boot();
  await app.browser.action.onClicked.fire(app.sourceTab);
  assert.equal(app.client.state.source.tabId, 17);
  assert.equal(app.client.state.source.windowId, 4);
  assert.equal(app.calls.creates.at(-1).type, 'sidebar');
  assert.equal(app.calls.captures.length, 0, 'Opening Jarvis itself does not capture');
  const result = await app.browser.runtime.onMessage.fire({ type: 'jarvis:command', action: 'capture' }, ownSender);
  assert.equal(result.ok, true);
  assert.equal(app.calls.captures[0].windowId, 4, 'Capture must use the selected browser window, never the focused pop-out');
  assert.equal(app.client.state.draft.attachment.source.url, app.sourceTab.url);
  assert.equal(app.client.state.draft.attachment.width, 1024);
  assert.equal(app.calls.uploads, 0);
  assert.equal(app.calls.sends, 0);
  assert.equal(app.calls.network, 0);
});

test('panel capture uses the current tab after a switch, not the previous toolbar source', async () => {
  const app = await boot();
  await app.browser.action.onClicked.fire(app.sourceTab);
  app.sourceTab.active = false;
  app.normalTabs.set(18, {...app.sourceTab, id: 18, active: true, url: 'https://example.test/new-tab'});
  const result = await app.browser.runtime.onMessage.fire({type: 'jarvis:command', action: 'capture', payload: {windowId: 4}}, ownSender);
  assert.equal(result.ok, true);
  assert.equal(app.client.state.draft.attachment.source.tabId, 18);
});

test('menu capture completes on the command queue before a server switch', async () => {
  const app = await boot({deferCapture: true});
  app.client.state.settings.serverUrl = 'https://server-a.test';
  const menu = app.browser.menus.onClicked.fire({menuItemId: MENU_IDS.capture}, app.sourceTab);
  await tick();
  assert.equal(app.calls.captures.length, 1);
  const config = app.browser.runtime.onMessage.fire({type: 'jarvis:command', action: 'configure', payload: {serverUrl: 'https://server-b.test'}}, ownSender);
  await tick();
  assert.equal(app.client.state.settings.serverUrl, 'https://server-a.test');
  app.releaseCapture();
  await menu; await config;
  assert.equal(app.client.state.settings.serverUrl, 'https://server-b.test');
  assert.equal(app.client.state.draft.attachment, null, 'Old capture cannot arrive after changing servers');
});

test('view heartbeat gets a pong without checkpointing or contacting the server', async () => {
  const app = await boot(); const port = viewPort();
  await app.browser.runtime.onConnect.fire(port); await tick();
  const before = app.calls.checkpoints;
  await port.onMessage.fire({type: 'ping'});
  assert.equal(port.messages.at(-1).type, 'pong');
  assert.equal(app.calls.checkpoints, before);
  assert.equal(app.calls.network, 0);
  await app.browser.runtime.onMessage.fire({type: 'jarvis:command', action: 'openPopout'}, ownSender);
  assert.equal(app.calls.creates.at(-1).type, 'popup');
});

test('pop-out remembers normal-window focus when Firefox returns the pop-out as last focused', async () => {
  const app = await boot();
  const stored = [];
  app.browser.storage.session.set = async value => stored.push(value);
  app.browser.windows.get = async id => ({id, type: [4, 5].includes(id) ? 'normal' : 'popup'});
  app.browser.windows.getAll = async () => [{id: 4, type: 'normal'}, {id: 5, type: 'normal'}, {id: 90, type: 'popup'}];
  app.browser.windows.getLastFocused = async () => ({id: 90, type: 'popup'});
  app.normalTabs.set(19, {...app.sourceTab, id: 19, windowId: 5, active: true});
  const before = app.calls.checkpoints;
  await app.browser.windows.onFocusChanged.fire(5);
  await app.browser.windows.onFocusChanged.fire(90);
  assert.equal(stored.at(-1).jarvisSourceWindowId, 5);
  assert.equal(app.calls.checkpoints, before, 'Remembering focus must not rewrite chat or image state');
  const result = await app.browser.runtime.onMessage.fire({type: 'jarvis:command', action: 'capture'}, ownSender);
  assert.equal(result.ok, true);
  assert.equal(app.calls.captures.at(-1).windowId, 5);
});

test('right-click handlers stage selection, exact clicked link and screenshot without auto-send', async () => {
  const app = await boot();
  await app.browser.menus.onClicked.fire({ menuItemId: MENU_IDS.selection, selectionText: 'Selected failure output' }, app.sourceTab);
  assert.equal(app.client.state.draft.context.text, 'Selected failure output');
  assert.equal(app.client.state.source.tabId, app.sourceTab.id);
  await app.browser.menus.onClicked.fire({ menuItemId: MENU_IDS.link, linkUrl: 'https://docs.example.test/error' }, app.sourceTab);
  assert.equal(app.client.state.draft.context.url, 'https://docs.example.test/error');
  await app.browser.menus.onClicked.fire({ menuItemId: MENU_IDS.capture }, app.sourceTab);
  assert.equal(app.calls.captures.length, 1);
  assert.equal(app.calls.sends, 0);
  assert.equal(app.calls.uploads, 0);
  assert.equal(app.calls.network, 0);
});
