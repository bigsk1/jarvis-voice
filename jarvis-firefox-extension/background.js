import './vendor/socket.io.min.js';
import {JarvisClient} from './core/client.js';
import {captureSource} from './browser/capture.js';
import {normalizeSource, resolveCurrentSource} from './browser/source.js';
import {setupMenus} from './browser/menus.js';

const views = new Set();
const panelUrl = browser.runtime.getURL('ui/panel.html');
const client = new JarvisClient({
  storage: browser.storage, permissions: browser.permissions, ioFactory: globalThis.io,
  onState: state => {
    for (const port of views) {
      try { port.postMessage({type: 'state', state}); }
      catch { views.delete(port); }
    }
  },
});
let lastBrowserWindowId = null;
const ready = Promise.all([client.restore(), browser.storage.session.get('jarvisSourceWindowId')]).then(([, saved]) => {
  if (Number.isInteger(saved.jarvisSourceWindowId)) lastBrowserWindowId = saved.jarvisSourceWindowId;
});
let commands = Promise.resolve();
let focusUpdates = Promise.resolve();

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
  // Actual message activity keeps Firefox's event page alive while a view is
  // open. An idle connected port alone does not. This never contacts Jarvis.
  port.onMessage.addListener(message => {
    if (message?.type === 'ping') {
      try { port.postMessage({type: 'pong'}); } catch { views.delete(port); }
    }
  });
  port.onDisconnect.addListener(() => views.delete(port));
  ready.then(() => {
    port.postMessage({type: 'state', state: client.state});
    return wakeConnection();
  }).catch(report);
});

const actions = {
  openPopout: () => openPanel(),
  configure: payload => client.configure(payload),
  connect: () => client.connect(),
  login: payload => client.login(payload.password),
  logout: () => client.logout(),
  setDraft: payload => client.setDraft(payload.text),
  send: payload => client.send(payload.text),
  cancel: () => client.cancel(),
  setMode: payload => client.setMode(payload.mode),
  listConversations: () => client.listConversations(),
  loadConversation: payload => client.loadConversation(payload.conversationId),
  newConversation: () => client.newConversation(),
  removeAttachment: () => client.removeAttachment(),
  capture: async payload => {
    client.requireIdle();
    await focusUpdates;
    const source = await resolveCurrentSource(browser, payload.windowId ?? null, lastBrowserWindowId);
    const attachment = await captureSource(browser, source);
    await client.stage({attachment, source: attachment.source});
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
      await rememberBrowserWindow(source.windowId);
      client.requireIdle();
      if (action.kind === 'capture') {
        const attachment = await captureSource(browser, source);
        await client.stage({attachment, source});
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
  if (!(removed.origins || []).length) return;
  await ready;
  if (client.state.settings.serverUrl) {
    const {originPermission} = await import('./core/connection.js');
    if (!await browser.permissions.contains({origins: [originPermission(client.state.settings.serverUrl)]})) {
      await client.logout();
      client.state.notice = 'Server access was removed in Firefox. Grant it again in Settings to reconnect.';
      client.changed();
    }
  }
});
