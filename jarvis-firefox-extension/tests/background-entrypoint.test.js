import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
import { captureSource as captureActual } from '../browser/capture.js';
import { capturePageContent as capturePageActual } from '../browser/page-content.js';
import { normalizeSource, resolveCurrentSource } from '../browser/source.js';
import { setupMenus, MENU_IDS } from '../browser/menus.js';
import { setupCompletionSignals, COMPLETION_ALARM } from '../browser/completion.js';
import { originPermission } from '../core/connection.js';
import { normalizePageLink } from '../core/page-link.js';
import { TalkBridge } from '../browser/talk.js';

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
  const calls = { captures: [], creates: [], updates: [], stages: [], badges: [], notifications: [], reads: [], checkpoints: 0, sends: 0, uploads: 0, connects: 0, closes: 0, network: 0 };
  const session = {};
  const alarms = new Map();
  const sourceTab = { id: 17, windowId: 4, active: true, url: 'https://example.test/dashboard', title: 'Source dashboard' };
  const normalTabs = new Map([[sourceTab.id, sourceTab]]);
  let releaseCapture;
  const captureGate = new Promise(resolve => { releaseCapture = resolve; });
  const browser = {
    runtime: { id: EXTENSION_ID, getURL: path => `moz-extension://companion-test/${path}`, onConnect: event(), onMessage: event(), onStartup: event(), onInstalled: event() },
    action: { onClicked: event(), setBadgeText: async value => calls.badges.push(value.text), setBadgeBackgroundColor: async () => {}, setTitle: async () => {} },
    alarms: {onAlarm: event(), get: async name => alarms.get(name), create: async (name, value) => alarms.set(name, value), clear: async name => alarms.delete(name)},
    notifications: {onClicked: event(), create: async (id, value) => calls.notifications.push({id, ...value}), clear: async () => {}},
    sidebarAction: {open: async () => calls.creates.push({type: 'sidebar'})},
    storage: {session: {get: async () => structuredClone(session), set: async value => Object.assign(session, structuredClone(value))}},
    permissions: { onRemoved: event(), onAdded: event(), contains: async () => true },
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
    scripting: {
      executeScript: async ({ target }) => {
        const tab = normalTabs.get(target.tabId);
        calls.scripts = calls.scripts || [];
        calls.scripts.push(target.tabId);
        return [{ result: {
          title: tab.title, url: tab.url, empty: false, truncated: false, charCount: 24,
          markdown: `# ${tab.title}\n\n- URL: ${tab.url}\n\n## Page\nDashboard body\n`,
          capturedAt: '2026-09-14T00:00:00.000Z',
        } }];
      },
    },
  };
  let restored;
  const restoring = new Promise(resolve => { restored = resolve; });
  let client;
  class Client {
    constructor(options) {
      client = this;
      this.options = options;
      this.state = { settings: {}, connection: { status: 'connected' }, source: null, draft: { text: '', attachment: null, context: null, page: null }, messages: [], conversations: [], run: null };
      this.intent = true;
      this.authScope = 'test-session';
      this.transport = { socket: { connected: true }, close: () => { calls.closes += 1; }, upload: () => { calls.uploads += 1; } };
    }
    restore() { return restoring; }
    requireIdle() { if (this.state.run?.status === 'running') throw new Error('A request is active'); }
    async checkpoint() { calls.checkpoints += 1; }
    publish() { this.options.onState(this.state); }
    changed() { this.publish(); }
    async stage(value) { calls.stages.push(value); this.state.source = value.source; this.state.draft.attachment = value.attachment || null; this.state.draft.context = value.context || null; this.state.draft.page = value.page || null; this.publish(); }
    async setDraft(text) { this.state.draft.text = text; this.publish(); }
    async includePage(source) { this.requireIdle(); this.state.draft.pageLink = normalizePageLink(source); this.publish(); }
    async removePageLink() { this.requireIdle(); this.state.draft.pageLink = null; this.publish(); }
    async configure(settings) { this.state.settings = settings; this.state.draft = {text: '', attachment: null, context: null, page: null}; }
    async connect() { calls.connects += 1; }
    recover() { this.publish(); }
    async updatePreferences(value) { this.state.settings.preferences = {...this.state.settings.preferences, ...value}; this.publish(); }
    async readConversation(id) { calls.reads.push(id); return this.savedConversation; }
    async findSubmittedConversation() { return null; }
    async loadConversation(id) { this.requireIdle(); this.state.conversationId = id; this.publish(); }
    async send() { calls.sends += 1; }
    async decideApproval(approved) { calls.approvals = [...(calls.approvals || []), approved]; }
    async logout() { calls.closes += 1; this.transport = null; }
  }
  const captureSource = (api, source) => captureActual(api, source, {
    decodeImage: async () => ({ width: 1920, height: 1080 }),
    createCanvas: () => ({ getContext: () => ({ fillRect() {}, drawImage() {} }), toDataURL: () => 'data:image/jpeg;base64,c291cmNl' }),
    now: () => '2026-09-14T00:00:00.000Z',
  });
  const capturePageContent = (api, source) => capturePageActual(api, source, {
    now: () => '2026-09-14T00:00:00.000Z',
  });
  const sandbox = { browser, JarvisClient: Client, TalkBridge, captureSource, capturePageContent, normalizeSource, resolveCurrentSource, setupMenus, setupCompletionSignals, originPermission, URL, console, setTimeout, clearTimeout, fetch: () => { calls.network += 1; throw new Error('Unexpected network request'); } };
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
  for (const api of [app.browser.runtime.onMessage, app.browser.runtime.onConnect, app.browser.action.onClicked, app.browser.menus.onClicked, app.browser.runtime.onInstalled, app.browser.runtime.onStartup, app.browser.permissions.onRemoved, app.browser.windows.onFocusChanged, app.browser.alarms.onAlarm, app.browser.notifications.onClicked]) assert.equal(api.listeners.length, 1);
  const pending = app.browser.runtime.onMessage.fire({ type: 'jarvis:state' }, ownSender);
  app.restored();
  assert.equal((await pending).ok, true);
  assert.equal(app.calls.network, 0);
});

test('approval decision remains available while Talk owns the active turn', async () => {
  const app = await boot();
  const bridge = vm.runInContext('talk', app.context);
  bridge.owner = {id: 'talk-turn'};
  app.client.state.run = {status: 'running', messageId: 'r1'};
  const reply = await app.browser.runtime.onMessage.fire({type: 'jarvis:command',
    action: 'decideApproval', payload: {approved: false}}, ownSender);
  assert.equal(reply.ok, true);
  assert.deepEqual(app.calls.approvals, [false]);
  bridge.owner = null;
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
  assert.equal(port.messages.filter(message => message.type === 'state').length, 1);
  assert.deepEqual(port.messages.find(message => message.type === 'talk:owner'), {type: 'talk:owner', sessionId: null});
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
  assert.equal(app.client.state.draft.page.url, app.sourceTab.url);
  assert.match(app.client.state.draft.page.markdown, /Dashboard body/);
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

test('include page resolves the current sidebar tab and stages only a fixed link', async () => {
  const app = await boot();
  await app.browser.action.onClicked.fire(app.sourceTab);
  assert.equal(app.client.state.draft.pageLink, undefined, 'Opening the sidebar does not attach its page');
  app.sourceTab.active = false;
  const video = {...app.sourceTab, id: 18, active: true, title: 'Video', url: 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'};
  app.normalTabs.set(18, video);
  const result = await app.browser.runtime.onMessage.fire({type: 'jarvis:command', action: 'includePage', payload: {windowId: 4}}, ownSender);
  assert.equal(result.ok, true);
  assert.deepEqual(app.client.state.draft.pageLink, {title: video.title, url: video.url});
  video.url = 'https://example.test/another-page';
  assert.match(app.client.state.draft.pageLink.url, /youtube/);
  assert.equal(app.calls.captures.length, 0);
  assert.equal(app.calls.scripts, undefined);
  assert.equal(app.calls.network + app.calls.uploads + app.calls.sends, 0);
  await app.browser.runtime.onMessage.fire({type: 'jarvis:command', action: 'removePageLink'}, ownSender);
  assert.equal(app.client.state.draft.pageLink, null);
});

test('include page rejects inaccessible, private and browser pages without changing the draft', async () => {
  for (const change of [{url: undefined}, {incognito: true}, {url: 'about:config'}, {pendingUrl: 'https://example.test/loading'}]) {
    const app = await boot();
    Object.assign(app.sourceTab, change);
    const result = await app.browser.runtime.onMessage.fire({type: 'jarvis:command', action: 'includePage', payload: {windowId: 4}}, ownSender);
    assert.equal(result.ok, false, JSON.stringify(change));
    assert.equal(app.client.state.draft.pageLink, undefined);
    assert.equal(app.calls.captures.length + app.calls.network, 0);
  }
});

test('right-click Include page link preserves other staged content without capturing', async () => {
  const app = await boot();
  app.client.state.draft.text = 'What is this about?';
  app.client.state.draft.context = {kind: 'selection', text: 'A quote'};
  await app.browser.menus.onClicked.fire({menuItemId: MENU_IDS.page, pageUrl: app.sourceTab.url}, app.sourceTab);
  assert.deepEqual(app.client.state.draft.pageLink, {title: app.sourceTab.title, url: app.sourceTab.url});
  assert.equal(app.client.state.draft.text, 'What is this about?');
  assert.equal(app.client.state.draft.context.text, 'A quote');
  assert.equal(app.calls.captures.length + app.calls.sends + app.calls.network, 0);
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
  await app.browser.menus.onClicked.fire({ menuItemId: MENU_IDS.image, srcUrl: 'https://images.example.test/chart.png' }, app.sourceTab);
  assert.equal(app.client.state.draft.context.kind, 'image');
  assert.equal(app.client.state.draft.context.url, 'https://images.example.test/chart.png');
  await app.browser.menus.onClicked.fire({ menuItemId: MENU_IDS.capture }, app.sourceTab);
  assert.equal(app.calls.captures.length, 1);
  assert.equal(app.calls.sends, 0);
  assert.equal(app.calls.uploads, 0);
  assert.equal(app.calls.network, 0);
});

test('notification preferences enforce optional permission and update without reconnecting', async () => {
  const app = await boot();
  app.browser.permissions.contains = async () => false;
  const command = {type: 'jarvis:command', action: 'updatePreferences', payload: {desktopNotifications: true}};
  assert.equal((await app.browser.runtime.onMessage.fire(command, ownSender)).ok, false);
  app.browser.permissions.contains = async () => true;
  assert.equal((await app.browser.runtime.onMessage.fire(command, ownSender)).ok, true);
  assert.equal(app.client.state.settings.preferences.desktopNotifications, true);
  await app.browser.permissions.onRemoved.fire({permissions: ['notifications']});
  assert.equal(app.client.state.settings.preferences.desktopNotifications, false);
  assert.equal(app.calls.connects, 0);
});

test('alarm observes completion with all views closed and never connects or resends work', async () => {
  const app = await boot();
  app.client.state.settings = {serverUrl: 'https://jarvis.example.test', preferences: {desktopNotifications: true}};
  app.client.state.submittedRequests = [{requestId: 'r1', conversationId: 'c1', mode: 'cloud', startedAt: Date.now()}];
  app.client.state.run = {requestId: 'r1', conversationId: 'c1', status: 'running'};
  app.client.savedConversation = {id: 'c1', messages: [{role: 'assistant', content: 'A result', data: {_web_message_id: 'r1', _run_status: 'completed'}}]};
  app.client.changed(); await tick();
  assert.equal(app.calls.badges.at(-1), '…');
  app.client.transport = null;
  await app.browser.alarms.onAlarm.fire({name: COMPLETION_ALARM});
  assert.deepEqual(app.calls.reads, ['c1']);
  assert.equal(app.calls.notifications.length, 1);
  assert.equal(app.calls.badges.at(-1), '1');
  assert.equal(app.calls.connects, 0);
  assert.equal(app.calls.sends, 0);
  await app.browser.alarms.onAlarm.fire({name: COMPLETION_ALARM});
  assert.equal(app.calls.notifications.length, 1);
});

test('only a focused matching conversation suppresses its completion notification', async () => {
  const app = await boot();
  app.client.state.settings = {serverUrl: 'https://jarvis.example.test', preferences: {desktopNotifications: true}};
  app.client.state.conversationId = 'c1';
  app.client.state.submittedRequests = [{requestId: 'r1', conversationId: 'c1', startedAt: Date.now()}];
  const port = viewPort(); await app.browser.runtime.onConnect.fire(port); await tick();
  await port.onMessage.fire({type: 'viewStatus', visible: true, conversationId: 'c1'});
  app.client.state.run = {requestId: 'r1', conversationId: 'c1', status: 'completed'};
  app.client.changed(); await tick();
  assert.equal(app.calls.notifications.length, 0);
  assert.equal(app.calls.badges.at(-1), '');
  port.disconnect();
  app.client.state.submittedRequests.push({requestId: 'r2', conversationId: 'c1', startedAt: Date.now()});
  app.client.state.run = {requestId: 'r2', conversationId: 'c1', status: 'completed'};
  app.client.changed(); await tick();
  assert.equal(app.calls.notifications.length, 1);
  assert.equal(app.calls.badges.at(-1), '1');
  await app.browser.notifications.onClicked.fire(app.calls.notifications[0].id);
  assert.equal(app.calls.creates.at(-1).type, 'popup');
  assert.equal(app.calls.badges.at(-1), '');
  assert.equal(app.calls.sends, 0);
});

test('notification click cannot load an old conversation after a queued server switch', async () => {
  const app = await boot();
  app.client.state.settings = {serverUrl: 'https://first.example.test', preferences: {desktopNotifications: true}};
  app.client.state.submittedRequests = [{requestId: 'r1', conversationId: 'c1', startedAt: Date.now()}];
  app.client.state.run = {requestId: 'r1', conversationId: 'c1', status: 'completed'};
  app.client.changed(); await tick();
  assert.equal(app.calls.notifications.length, 1);
  app.browser.windows.getAll = async () => {
    app.client.authScope = 'new-session';
    app.client.state.settings.serverUrl = 'https://second.example.test';
    app.client.state.submittedRequests = [];
    return [];
  };
  await app.browser.notifications.onClicked.fire(app.calls.notifications[0].id);
  assert.equal(app.calls.connects, 0);
  assert.equal(app.client.state.conversationId, undefined);
  assert.match(app.client.state.notice, /sign-in changed/);
});
