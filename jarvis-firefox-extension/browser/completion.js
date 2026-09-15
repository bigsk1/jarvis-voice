const STORAGE_KEY = 'jarvisCompletionSignals';
export const COMPLETION_ALARM = 'jarvis-completion-check';
const TERMINAL = new Set(['completed', 'failed', 'cancelled', 'interrupted', 'rejected', 'unconfirmed']);
const MAX_AGE = 7 * 24 * 60 * 60 * 1000;
const validId = value => typeof value === 'string' && /^[A-Za-z0-9_-]{1,150}$/.test(value);

/** Read only the tracked request's result, even when the conversation has moved on. */
export function conversationOutcome(conversation, requestId) {
  if (!conversation || !validId(conversation.id)) return null;
  const messages = Array.isArray(conversation.messages) ? conversation.messages : [];
  const answer = messages.find(message => message.role === 'assistant' && message.data?._web_message_id === requestId);
  const user = messages.find(message => message.role === 'user' && message.data?._request_id === requestId);
  const run = conversation.run?.message_id === requestId ? conversation.run :
    user?.data?._run?.message_id === requestId ? user.data._run : null;
  if (!run && !user && !answer) return null;
  const status = run?.status || answer?.data?._run_status;
  return {
    conversationId: conversation.id,
    status: TERMINAL.has(status) ? status : 'pending',
    text: typeof answer?.content === 'string' ? answer.content : '',
  };
}

/** Browser-only signals. HTTP recovery observes saved work; it never submits it. */
export function setupCompletionSignals(browser, {
  getClient, readConversation, findConversation = async () => null,
  openConversation, isConversationVisible = () => false, now = () => Date.now(),
}) {
  let store = {scope: null, requests: []};
  let queue = Promise.resolve();
  let savedJson = '';
  let lastBadge = '';
  let alarmPending = null;
  let disposed = false;
  let notificationsAttached = false;
  const loading = browser.storage.session.get(STORAGE_KEY).then(saved => {
    const value = saved[STORAGE_KEY];
    if (value && typeof value.scope === 'string' && Array.isArray(value.requests)) {
      store = {scope: value.scope, requests: value.requests.filter(item => validId(item.requestId)).slice(-256)};
    }
    savedJson = JSON.stringify(store);
  });

  function enqueue(action) {
    const result = queue.catch(() => {}).then(async () => {
      await loading;
      if (!disposed) return action();
    });
    queue = result;
    return result;
  }

  function scopeFor(client) {
    if (!client.intent || !client.authScope || !client.state.settings.serverUrl ||
        client.state.connection.authRequired && !client.token) return null;
    return `${client.state.settings.serverUrl}\n${client.authScope}`;
  }

  async function persist() {
    const json = JSON.stringify(store);
    if (json === savedJson) return;
    await browser.storage.session.set({[STORAGE_KEY]: structuredClone(store)});
    savedJson = json;
  }

  async function clearNotifications(requests) {
    if (!browser.notifications?.clear) return;
    await Promise.all(requests.filter(item => item.notificationId).map(item =>
      browser.notifications.clear(item.notificationId).catch(() => {})));
  }

  async function setScope(client) {
    const scope = scopeFor(client);
    if (store.scope === scope) return;
    const previous = store.requests;
    store = {scope, requests: []};
    await persist();
    await clearNotifications(previous);
  }

  async function updateBrowser(preferences = {}) {
    const unread = store.requests.filter(item => item.unread);
    const pending = store.requests.some(item => item.status === 'pending');
    const failed = unread.some(item => item.status !== 'completed');
    const text = preferences.showBadge === false ? '' : unread.length ?
      String(Math.min(unread.length, 99)) : pending ? '…' : '';
    const title = unread.length ? `Jarvis: ${unread.length} unread result${unread.length === 1 ? '' : 's'}` :
      pending ? 'Jarvis is working' : 'Open Jarvis sidebar';
    const color = unread.length ? failed ? '#aa4937' : '#24765c' : '#5852a5';
    const badge = JSON.stringify([text, title, color]);
    if (badge !== lastBadge) {
      await Promise.all([
        browser.action.setBadgeText({text}),
        browser.action.setBadgeBackgroundColor({color}),
        browser.action.setTitle({title}),
      ]);
      lastBadge = badge;
    }
    if (pending !== alarmPending) {
      if (pending) {
        if (!await browser.alarms.get(COMPLETION_ALARM)) {
          await browser.alarms.create(COMPLETION_ALARM, {delayInMinutes: 1, periodInMinutes: 1});
        }
      } else await browser.alarms.clear(COMPLETION_ALARM);
      alarmPending = pending;
    }
  }

  function hasDisplayedResult(client, item) {
    const state = client.state;
    if (state.conversationId !== item.conversationId) return false;
    const run = state.run;
    if ((run?.requestId === item.requestId || run?.messageId === item.requestId) && TERMINAL.has(run.status)) return true;
    return (state.messages || []).some(message => message.role === 'assistant' &&
      [item.requestId, `assistant-${item.requestId}`].includes(message.id));
  }

  function isResultVisible(client, item) {
    return isConversationVisible(item.conversationId) && hasDisplayedResult(client, item);
  }

  async function finish(client, item, status, text = '') {
    if (item.status !== 'pending' || !TERMINAL.has(status)) return;
    item.status = status;
    const quiet = ['cancelled', 'rejected', 'unconfirmed'].includes(status);
    item.unread = !quiet && !isResultVisible(client, item);
    const preferences = client.state.settings.preferences || {};
    const notify = item.unread && preferences.desktopNotifications === true && validId(item.conversationId);
    if (notify) item.notificationId = `jarvis-result-${client.authScope}-${item.requestId}`;
    // Commit the terminal decision before showing it. Repeated socket snapshots
    // and event-page wakes cannot emit the same completion again.
    await persist();
    if (!notify || !browser.notifications?.create) return;
    let permitted = false;
    try { permitted = await browser.permissions.contains({permissions: ['notifications']}); } catch { /* Permission disappeared. */ }
    if (!permitted || scopeFor(client) !== store.scope) return;
    // Permission/storage checks yield. An opt-out or a newly displayed answer
    // during that time must take effect before any OS notification is created.
    if (isResultVisible(client, item)) {
      item.unread = false;
      await persist();
      return;
    }
    const currentPreferences = client.state.settings.preferences || {};
    if (currentPreferences.desktopNotifications !== true) return;
    const preview = status === 'completed' && currentPreferences.notificationPreview === true ?
      String(text).replace(/\s+/g, ' ').trim().slice(0, 220) : '';
    try {
      await browser.notifications.create(item.notificationId, {
        type: 'basic', iconUrl: browser.runtime.getURL('assets/jarvis-96.png'),
        title: status === 'completed' ? 'Jarvis finished your request' : 'Jarvis could not finish your request',
        message: preview || 'Open the conversation to review the result.',
      });
    } catch { /* OS notification failures must not affect the chat or badge. */ }
  }

  async function synchronize(client, state = client.state) {
    await setScope(client);
    const scope = store.scope;
    if (store.scope) {
      for (const request of (state.submittedRequests || []).slice(-64)) {
        if (scopeFor(client) !== scope) break;
        if (!validId(request.requestId)) continue;
        let item = store.requests.find(entry => entry.requestId === request.requestId);
        if (!item) {
          item = {
            requestId: request.requestId, conversationId: null, mode: request.mode,
            startedAt: Number.isFinite(request.startedAt) ? request.startedAt : Date.parse(request.startedAt) || now(),
            status: 'pending', unread: false,
          };
          store.requests.push(item);
        }
        if (validId(request.conversationId)) item.conversationId = request.conversationId;
        const run = state.run?.requestId === item.requestId || state.run?.messageId === item.requestId ? state.run : null;
        if (validId(run?.conversationId)) item.conversationId = run.conversationId;
        const answer = (state.messages || []).find(message => message.role === 'assistant' &&
          [item.requestId, `assistant-${item.requestId}`].includes(message.id));
        await finish(client, item, TERMINAL.has(request.status) ? request.status : run?.status, answer?.content);
      }
      for (const item of store.requests) {
        if (item.status === 'pending' && now() - item.startedAt > MAX_AGE) item.status = 'expired';
        if (item.unread && isResultVisible(client, item)) item.unread = false;
      }
      store.requests = store.requests.slice(-256);
    }
    await setScope(client);
    await persist();
    await updateBrowser(client.state.settings.preferences);
  }

  async function refresh() {
    const client = await getClient();
    await synchronize(client);
    const scope = store.scope;
    for (const item of store.requests.filter(entry => entry.status === 'pending')) {
      if (!scope || scopeFor(client) !== scope) break;
      try {
        const result = item.conversationId ? await readConversation(client, item.conversationId) :
          await findConversation(client, {...item});
        if (scopeFor(client) !== scope) break;
        const conversation = result?.conversation || result;
        if (item.conversationId && conversation?.id !== item.conversationId) continue;
        const outcome = conversationOutcome(conversation, item.requestId);
        if (!outcome) continue;
        item.conversationId = outcome.conversationId;
        await finish(client, item, outcome.status, outcome.text);
      } catch { /* Offline, missing, or unauthorized: never infer completion or resend. */ }
    }
    await setScope(client);
    await persist();
    await updateBrowser(client.state.settings.preferences);
  }

  function onAlarm(alarm) {
    if (alarm.name === COMPLETION_ALARM) return enqueue(refresh).catch(() => {});
  }

  function onClicked(notificationId) {
    return enqueue(async () => {
      const client = await getClient();
      await setScope(client);
      const item = store.requests.find(entry => entry.notificationId === notificationId);
      if (!item || !validId(item.conversationId)) return;
      const scope = store.scope;
      await openConversation(item.conversationId, item.mode, {
        authScope: client.authScope, serverUrl: client.state.settings.serverUrl,
      });
      if (scopeFor(client) !== scope) {
        await setScope(client);
        await updateBrowser(client.state.settings.preferences);
        return;
      }
      item.unread = false;
      await clearNotifications([item]);
      await persist();
      await updateBrowser(client.state.settings.preferences);
    }).catch(() => {});
  }

  function attachNotifications() {
    if (!notificationsAttached && browser.notifications?.onClicked) {
      browser.notifications.onClicked.addListener(onClicked);
      notificationsAttached = true;
    }
  }

  function onPermissionsAdded(permissions) {
    if (permissions.permissions?.includes('notifications')) attachNotifications();
  }

  // These registrations run before any await so Firefox can wake an MV3 page.
  browser.alarms.onAlarm.addListener(onAlarm);
  browser.permissions.onAdded.addListener(onPermissionsAdded);
  attachNotifications();

  return {
    // Read the owner's latest state when queued work starts. A snapshot queued
    // before logout must never be attributed to the following login/server.
    observe() { return enqueue(async () => synchronize(await getClient())); },
    refresh() { return enqueue(refresh); },
    markRead(conversationId) {
      return enqueue(async () => {
        const client = await getClient();
        await setScope(client);
        const items = store.requests.filter(item => item.conversationId === conversationId && item.unread && hasDisplayedResult(client, item));
        for (const item of items) item.unread = false;
        await clearNotifications(items);
        await persist();
        await updateBrowser(client.state.settings.preferences);
      });
    },
    dispose() {
      disposed = true;
      browser.alarms.onAlarm.removeListener(onAlarm);
      browser.permissions.onAdded.removeListener(onPermissionsAdded);
      if (notificationsAttached) browser.notifications?.onClicked.removeListener(onClicked);
    },
  };
}
