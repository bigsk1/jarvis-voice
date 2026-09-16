import './vendor/socket.io.min.js';
import {JarvisClient} from './core/client.js';
import {captureSource} from './browser/capture.js';
import {capturePageContent} from './browser/page-content.js';
import {normalizeSource, resolveCurrentSource} from './browser/source.js';
import {setupMenus} from './browser/menus.js';
import {setupCompletionSignals} from './browser/completion.js';
import {originPermission} from './core/connection.js';
import {TalkBridge} from './browser/talk.js';

const views = new Set();
const viewStatus = new Map();
const stateWaiters = new Set();
let completion = null;
let talk = null;
const panelUrl = browser.runtime.getURL('ui/panel.html');
const client = new JarvisClient({
  storage: browser.storage, permissions: browser.permissions, ioFactory: globalThis.io,
  onState: state => {
    talk?.observe(state);
    for (const port of views) {
      try { port.postMessage({type: 'state', state}); }
      catch { views.delete(port); viewStatus.delete(port); }
    }
    for (const check of stateWaiters) check(state);
    completion?.observe(state).catch(() => {});
  },
  onServerEvent: (event, data) => talk?.event(event, data),
});
talk = new TalkBridge(client, enqueue, message => {
  for (const port of views) talk.post(port, message);
});
let lastBrowserWindowId = null;
const ready = Promise.all([client.restore(), browser.storage.session.get('jarvisSourceWindowId')]).then(([, saved]) => {
  if (Number.isInteger(saved.jarvisSourceWindowId)) lastBrowserWindowId = saved.jarvisSourceWindowId;
});
let commands = Promise.resolve();
let focusUpdates = Promise.resolve();

completion = setupCompletionSignals(browser, {
  getClient: async () => { await ready; return client; },
  readConversation: (owner, id) => owner.readConversation(id),
  findConversation: (owner, request) => owner.findSubmittedConversation(request),
  isConversationVisible: id => Boolean(id) && [...viewStatus.values()].some(view =>
    view.visible && view.conversationId === id),
  openConversation: (id, mode, scope) => openNotifiedConversation(id, scope),
});
ready.then(() => completion.observe(client.state)).catch(() => {});

function waitForState(predicate, scope) {
  return new Promise((resolve, reject) => {
    const finish = error => {
      clearTimeout(timer);
      stateWaiters.delete(check);
      if (error) reject(error); else resolve();
    };
    const check = state => {
      if (client.authScope !== scope) return finish(new Error('The Jarvis sign-in changed. Open the conversation from History.'));
      if (['error', 'auth_required', 'unconfigured'].includes(state.connection.status)) {
        return finish(new Error('Connect to Jarvis, then open the conversation from History.'));
      }
      if (predicate(state)) finish();
    };
    const timer = setTimeout(() => finish(new Error('The conversation is not ready yet. Reconnect and open it from History.')), 22000);
    stateWaiters.add(check);
    check(client.state);
  });
}

async function openNotifiedConversation(id, expectedScope) {
  const scope = expectedScope?.authScope ?? client.authScope;
  const serverUrl = expectedScope?.serverUrl ?? client.state.settings.serverUrl;
  await openPanel();
  try {
    await enqueue(async () => {
      talk.requireIdle();
      if (client.authScope !== scope || client.state.settings.serverUrl !== serverUrl) {
        throw new Error('The Jarvis sign-in changed. Open the conversation from History.');
      }
      await client.connect();
      await waitForState(state => state.connection.status === 'connected', scope);
      if (client.state.conversationId === id) {
        client.recover();
        client.changed();
      } else await client.loadConversation(id);
      await waitForState(state => state.connection.status === 'connected' && state.conversationId === id, scope);
    });
  } catch (error) { report(error); throw error; }
}

async function rememberBrowserWindow(windowId) {
  lastBrowserWindowId = windowId;
  await browser.storage.session.set({jarvisSourceWindowId: windowId});
}

// Firefox's getLastFocused window-type filter does not exclude our pop-out.
// Remember normal-window focus without cloning the chat or screenshot state.
browser.windows.onFocusChanged.addListener(windowId => {
  if (!Number.isInteger(windowId) || windowId < 0) return;
  focusUpdates = focusUpdates.catch(() => {}).then(async () => {
    await ready;
    let focused;
    try { focused = await browser.windows.get(windowId); } catch { return; }
    if (focused.type === 'normal' && !focused.incognito) await rememberBrowserWindow(focused.id);
  }).catch(report);
  return focusUpdates;
});

function enqueue(action) {
  const result = commands.catch(() => {}).then(async () => { await ready; return action(); });
  commands = result;
  return result;
}

// Firefox requires sidebar opening to remain within the browser user gesture.
function openSidebar() {
  return browser.sidebarAction.open().catch(report);
}

function fromView(sender) {
  if (sender?.id !== browser.runtime.id || sender?.tab?.incognito) return false;
  try {
    const url = new URL(sender.url);
    const expected = new URL(panelUrl);
    return url.protocol === expected.protocol && url.host === expected.host && url.pathname === expected.pathname;
  } catch { return false; }
}

function report(error) {
  client.state.notice = error.message || 'Jarvis could not complete this action.';
  client.changed();
}

async function openPanel() {
  const windows = await browser.windows.getAll({populate: true, windowTypes: ['popup']});
  const existing = windows.find(window => window.tabs?.some(tab => tab.url === panelUrl));
  if (existing) await browser.windows.update(existing.id, {focused: true});
  else await browser.windows.create({url: panelUrl, type: 'popup', width: 510, height: 780});
}

async function wakeConnection() {
  await ready;
  if (client.intent && !client.transport) await client.connect();
}

// These listeners must be installed synchronously on every MV3 event-page wake.
browser.runtime.onConnect.addListener(port => {
  if (port.name !== 'jarvis-ui' || !fromView(port.sender)) { port.disconnect(); return; }
  views.add(port);
  talk.attach(port);
  // Actual message activity keeps Firefox's event page alive while a view is
  // open. An idle connected port alone does not. This never contacts Jarvis.
  port.onMessage.addListener(message => {
    if (message?.type === 'talk:request') { talk.handle(port, message); return; }
    if (message?.type === 'ping') {
      try { port.postMessage({type: 'pong'}); } catch { views.delete(port); viewStatus.delete(port); }
    } else if (message?.type === 'viewStatus') {
      const id = typeof message.conversationId === 'string' && /^[A-Za-z0-9_-]{1,150}$/.test(message.conversationId) ? message.conversationId : null;
      const visible = message.visible === true;
      viewStatus.set(port, {visible, conversationId: id});
      if (visible && id && id === client.state.conversationId) completion.markRead(id).catch(() => {});
    }
  });
  port.onDisconnect.addListener(() => { views.delete(port); viewStatus.delete(port); talk.detach(port); });
  ready.then(() => {
    port.postMessage({type: 'state', state: client.state});
    return wakeConnection();
  }).catch(report);
});

const actions = {
  openPopout: () => openPanel(),
  microphonePermission: async payload => {
    const url = browser.runtime.getURL('ui/microphone.html');
    const windowId = Number.isInteger(payload.windowId) ? payload.windowId : (await browser.windows.getLastFocused()).id;
    const helper = browser.extension.getViews({type: 'tab', windowId}).find(view => view.location.href === url);
    const tab = helper && await helper.browser.tabs.getCurrent();
    if (tab) {
      await browser.windows.update(tab.windowId, {focused: true});
      await browser.tabs.update(tab.id, {active: true});
    } else await browser.tabs.create({url, windowId});
  },
  configure: payload => client.configure(payload),
  updatePreferences: async payload => {
    if (payload.desktopNotifications === true && !await browser.permissions.contains({permissions: ['notifications']})) {
      throw new Error('Allow Firefox notifications in Settings first.');
    }
    await client.updatePreferences(payload);
  },
  connect: () => client.connect(),
  login: payload => client.login(payload.password),
  logout: () => client.logout(),
  setDraft: payload => client.setDraft(payload.text, Object.hasOwn(payload, 'imageStageId') ? {imageStageId: payload.imageStageId} : {}),
  send: payload => client.send(payload.text),
  cancel: () => client.cancel(),
  setMode: payload => client.setMode(payload.mode),
  listConversations: () => client.listConversations(),
  loadConversation: payload => client.loadConversation(payload.conversationId),
  newConversation: () => client.newConversation(),
  removeAttachment: () => client.removeAttachment(),
  removeContext: () => client.removeContext(),
  removePage: () => client.removePage(),
  removePageLink: () => client.removePageLink(),
  includePage: async payload => {
    client.requireIdle();
    await focusUpdates;
    const source = await resolveCurrentSource(browser, payload.windowId ?? null, lastBrowserWindowId);
    await client.includePage(source);
  },
  capture: async payload => {
    client.requireIdle();
    await focusUpdates;
    const source = await resolveCurrentSource(browser, payload.windowId ?? null, lastBrowserWindowId);
    let page = null;
    let attachment = null;
    let pageError = null;
    if (client.state.capabilities?.text !== false) {
      try { page = await capturePageContent(browser, source); }
      catch (error) { pageError = error; }
    }
    try { attachment = await captureSource(browser, source); }
    catch (error) {
      if (!page) throw pageError || error;
      pageError = pageError || error;
    }
    await client.stage({
      attachment, page, source: attachment?.source || page.source,
      context: client.state.draft.context,
    });
    if (pageError) {
      client.state.notice = pageError.message;
      client.changed();
    }
  },
};

browser.runtime.onMessage.addListener((message, sender) => {
  if (!fromView(sender)) return Promise.resolve({ok: false, error: 'Only the Jarvis extension interface can perform this action.'});
  if (message?.type === 'jarvis:state') return ready.then(() => ({ok: true, state: client.state}));
  if (message?.type !== 'jarvis:command' || !Object.hasOwn(actions, message.action)) {
    return Promise.resolve({ok: false, error: 'Unknown Jarvis action.'});
  }
  // Serialize user commands so a delayed login/upload cannot write into a newly
  // selected server or conversation. Socket events can still update run state.
  return enqueue(async () => {
    try {
      if (!['openPopout', 'microphonePermission', 'updatePreferences', 'listConversations', 'connect'].includes(message.action)) talk.requireIdle();
      await actions[message.action](message.payload || {});
      return {ok: true, state: client.state};
    } catch (error) {
      report(error);
      return {ok: false, error: error.message, state: client.state};
    }
  });
});

browser.action.onClicked.addListener(async tab => {
  const opening = openSidebar();
  try {
    await enqueue(async () => {
      client.state.source = normalizeSource(tab);
      await rememberBrowserWindow(tab.windowId);
      await client.checkpoint();
      client.publish();
    });
  } catch (error) { report(error); }
  await opening;
});

const menus = setupMenus(browser, async action => {
  const opening = openSidebar();
  try {
    await enqueue(async () => {
      const source = normalizeSource(action.tab);
      talk.requireIdle();
      await rememberBrowserWindow(source.windowId);
      client.requireIdle();
      if (action.kind === 'capture') {
        let page = null;
        let attachment = null;
        let pageError = null;
        if (client.state.capabilities?.text !== false) {
          try { page = await capturePageContent(browser, source); }
          catch (error) { pageError = error; }
        }
        try { attachment = await captureSource(browser, source); }
        catch (error) {
          if (!page) throw pageError || error;
          pageError = pageError || error;
        }
        await client.stage({
          attachment, page, source: attachment?.source || page.source,
          context: client.state.draft.context,
        });
        if (pageError) {
          client.state.notice = pageError.message;
          client.changed();
        }
      } else if (action.kind === 'pageLink') {
        await client.includePage(source);
      } else if (action.kind === 'image') {
        await client.stage({source, context: {kind: 'image', url: action.imageUrl, title: source.title, text: ''}});
      } else {
        let url = source.url;
        if (action.kind === 'link') {
          const target = new URL(action.linkUrl);
          if (!['http:', 'https:'].includes(target.protocol)) throw new Error('Only HTTP(S) links can be sent to Jarvis.');
          url = target.href;
        }
        await client.stage({source, context: {text: String(action.selectionText || '').slice(0, 16000), url, title: source.title}});
      }
    });
  } catch (error) { report(error); }
  await opening;
});

browser.runtime.onStartup.addListener(() => menus.ensureMenus().catch(report));
browser.permissions.onRemoved.addListener(async removed => {
  await ready;
  if (removed.permissions?.includes('notifications')) {
    await enqueue(() => client.updatePreferences({desktopNotifications: false}));
  }
  if ((removed.origins || []).length && client.state.settings.serverUrl) {
    if (!await browser.permissions.contains({origins: [originPermission(client.state.settings.serverUrl)]})) {
      await client.logout();
      client.state.notice = 'Server access was removed in Firefox. Grant it again in Settings to reconnect.';
      client.changed();
    }
  }
});
