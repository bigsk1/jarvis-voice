import test from 'node:test';
import assert from 'node:assert/strict';
import {setupCompletionSignals, conversationOutcome, COMPLETION_ALARM} from '../browser/completion.js';

function event() {
  const listeners = new Set();
  return {
    listeners, addListener(listener) { listeners.add(listener); }, removeListener(listener) { listeners.delete(listener); },
    async emit(value) { return Promise.all([...listeners].map(listener => listener(value))); },
  };
}

function fixture({preferences = {}, stored = {}, permission = true} = {}) {
  const calls = {notifications: [], cleared: [], reads: [], opened: [], badge: [], titles: []};
  const data = structuredClone(stored);
  const alarms = new Map();
  const client = {
    authScope: 'session-a', intent: true, token: 'token-is-not-copied',
    state: {settings: {serverUrl: 'https://jarvis.example.test', preferences},
      connection: {status: 'connected', authRequired: true}, submittedRequests: [], messages: [], run: null},
  };
  const browser = {
    storage: {session: {
      async get(key) { return {[key]: structuredClone(data[key])}; },
      async set(value) { Object.assign(data, structuredClone(value)); },
    }},
    action: {
      async setBadgeText(value) { calls.badge.push(value.text); },
      async setBadgeBackgroundColor() {},
      async setTitle(value) { calls.titles.push(value.title); },
    },
    alarms: {
      onAlarm: event(), async get(name) { return alarms.get(name); },
      async create(name, options) { alarms.set(name, options); },
      async clear(name) { return alarms.delete(name); },
    },
    permissions: {onAdded: event(), async contains() { return permission; }},
    notifications: {
      onClicked: event(),
      async create(id, options) { calls.notifications.push({id, ...options}); },
      async clear(id) { calls.cleared.push(id); },
    },
    runtime: {getURL: path => `moz-extension://test/${path}`},
  };
  let conversation = null;
  let visible = false;
  const options = {
    getClient: async () => client,
    readConversation: async (_, id) => { calls.reads.push(id); return conversation; },
    findConversation: async () => conversation,
    openConversation: async (id, mode) => calls.opened.push({id, mode}),
    isConversationVisible: () => visible,
    now: () => 100000,
  };
  const controller = setupCompletionSignals(browser, options);
  function submit(requestId = 'request-a', conversationId = 'conversation-a') {
    client.state.conversationId = conversationId;
    client.state.submittedRequests.push({requestId, conversationId, mode: 'cloud', startedAt: 100000});
    client.state.run = {requestId, messageId: requestId, conversationId, status: 'running'};
  }
  function finish(status = 'completed', text = 'A private answer') {
    client.state.run.status = status;
    client.state.messages = [{role: 'assistant', id: `assistant-${client.state.run.requestId}`, content: text}];
  }
  return {controller, browser, client, calls, data, alarms, options, submit, finish,
    setConversation(value) { conversation = value; }, setVisible(value) { visible = value; }};
}

test('registers alarm and notification wake listeners synchronously, and disposes them', () => {
  const f = fixture();
  assert.equal(f.browser.alarms.onAlarm.listeners.size, 1);
  assert.equal(f.browser.notifications.onClicked.listeners.size, 1);
  assert.equal(f.browser.permissions.onAdded.listeners.size, 1);
  f.controller.dispose();
  assert.equal(f.browser.alarms.onAlarm.listeners.size, 0);
  assert.equal(f.browser.notifications.onClicked.listeners.size, 0);
});

test('default badge tracks running and unread extension requests without desktop notifications', async () => {
  const f = fixture();
  await f.controller.observe();
  assert.equal(f.calls.badge.at(-1), '');
  f.submit();
  await f.controller.observe();
  assert.equal(f.calls.badge.at(-1), '…');
  assert.deepEqual(f.alarms.get(COMPLETION_ALARM), {delayInMinutes: 1, periodInMinutes: 1});
  f.finish();
  await f.controller.observe();
  assert.equal(f.calls.badge.at(-1), '1');
  assert.equal(f.alarms.size, 0);
  assert.equal(f.calls.notifications.length, 0);
  await f.controller.markRead('conversation-a');
  assert.equal(f.calls.badge.at(-1), '');
});

test('unrelated loaded history never creates completion alerts or pending checks', async () => {
  const f = fixture({preferences: {desktopNotifications: true}});
  f.client.state.run = {requestId: 'other-client', status: 'completed'};
  await f.controller.observe();
  await f.controller.refresh();
  assert.equal(f.calls.notifications.length, 0);
  assert.equal(f.calls.reads.length, 0);
  assert.equal(f.alarms.size, 0);
});

test('generic notification is deduplicated across repeated live events and event-page reloads', async () => {
  const f = fixture({preferences: {desktopNotifications: true}});
  f.submit(); f.finish();
  await f.controller.observe();
  await f.controller.observe();
  assert.equal(f.calls.notifications.length, 1);
  assert.equal(f.calls.notifications[0].message, 'Open the conversation to review the result.');
  assert.match(f.calls.notifications[0].iconUrl, /jarvis-96\.png$/);
  assert.doesNotMatch(JSON.stringify(f.data), /private answer|token-is-not-copied/);
  f.controller.dispose();
  const restored = setupCompletionSignals(f.browser, f.options);
  await restored.observe();
  assert.equal(f.calls.notifications.length, 1);
  await f.browser.notifications.onClicked.emit(f.calls.notifications[0].id);
  assert.deepEqual(f.calls.opened, [{id: 'conversation-a', mode: 'cloud'}]);
  assert.equal(f.calls.badge.at(-1), '');
  restored.dispose();
});

test('preview is opt-in, bounded, and never saved in completion bookkeeping', async () => {
  const f = fixture({preferences: {desktopNotifications: true, notificationPreview: true}});
  f.submit(); f.finish('completed', `Secret answer\n${'x'.repeat(500)}`);
  await f.controller.observe();
  assert.equal(f.calls.notifications[0].message.length, 220);
  assert.match(f.calls.notifications[0].message, /^Secret answer x/);
  assert.doesNotMatch(JSON.stringify(f.data), /Secret answer/);
});

test('failed and interrupted work signals failure; cancellation and unconfirmed delivery stay quiet', async () => {
  for (const status of ['failed', 'interrupted', 'cancelled', 'unconfirmed']) {
    const f = fixture({preferences: {desktopNotifications: true, notificationPreview: true}});
    f.submit(); f.finish(status);
    await f.controller.observe();
    const quiet = ['cancelled', 'unconfirmed'].includes(status);
    assert.equal(f.calls.notifications.length, quiet ? 0 : 1, status);
    assert.equal(f.calls.badge.at(-1), quiet ? '' : '1', status);
    if (!quiet) {
      assert.match(f.calls.notifications[0].title, /could not finish/);
      assert.doesNotMatch(f.calls.notifications[0].message, /private answer/);
    }
  }
});

test('disabled badge and absent optional notification permission are respected', async () => {
  const f = fixture({preferences: {showBadge: false, desktopNotifications: true}, permission: false});
  f.submit(); f.finish();
  await f.controller.observe();
  assert.equal(f.calls.badge.at(-1), '');
  assert.equal(f.calls.notifications.length, 0);
});

test('results already visible in the extension are read without notifying', async () => {
  const f = fixture({preferences: {desktopNotifications: true}});
  f.setVisible(true);
  f.submit(); f.finish();
  await f.controller.observe();
  assert.equal(f.calls.notifications.length, 0);
  assert.equal(f.calls.badge.at(-1), '');
});

test('a stale visible conversation cannot consume a result recovered by HTTP', async () => {
  const f = fixture({preferences: {desktopNotifications: true}});
  f.setVisible(true);
  f.submit();
  f.setConversation({id: 'conversation-a', run: {message_id: 'request-a', status: 'completed'}, messages: []});
  await f.controller.refresh();
  await f.controller.markRead('conversation-a');
  assert.equal(f.calls.notifications.length, 1);
  assert.equal(f.calls.badge.at(-1), '1');
  f.finish();
  await f.controller.markRead('conversation-a');
  assert.equal(f.calls.badge.at(-1), '');
});

test('notification and preview opt-outs apply even during a pending permission check', async () => {
  for (const change of [{desktopNotifications: false}, {notificationPreview: false}]) {
    const f = fixture({preferences: {desktopNotifications: true, notificationPreview: true}});
    let release;
    let started;
    const checking = new Promise(resolve => { started = resolve; });
    f.browser.permissions.contains = () => {
      started();
      return new Promise(resolve => { release = resolve; });
    };
    f.submit(); f.finish();
    const observing = f.controller.observe();
    await checking;
    f.client.state.settings.preferences = {...f.client.state.settings.preferences, ...change};
    release(true);
    await observing;
    if (change.desktopNotifications === false) assert.equal(f.calls.notifications.length, 0);
    else assert.equal(f.calls.notifications[0].message, 'Open the conversation to review the result.');
  }
});

test('alarm recovers only matching saved work with sidebar closed and dedupes later live replay', async () => {
  const f = fixture({preferences: {desktopNotifications: true}});
  f.submit();
  await f.controller.observe();
  f.setConversation({id: 'conversation-a', run: {message_id: 'request-b', status: 'completed'}, messages: [
    {role: 'user', data: {_request_id: 'request-a', _run: {message_id: 'request-a', status: 'completed'}}},
    {role: 'assistant', content: 'Saved response', data: {_web_message_id: 'request-a', _run_status: 'completed'}},
  ]});
  await f.browser.alarms.onAlarm.emit({name: COMPLETION_ALARM});
  assert.deepEqual(f.calls.reads, ['conversation-a']);
  assert.equal(f.calls.notifications.length, 1);
  f.finish();
  await f.controller.observe();
  assert.equal(f.calls.notifications.length, 1);
});

test('a newer conversation run or bare assistant text cannot prove an older request completed', async () => {
  const f = fixture({preferences: {desktopNotifications: true}});
  f.submit();
  await f.controller.observe();
  f.setConversation({id: 'conversation-a', run: {message_id: 'other-request', status: 'completed'}, messages: [
    {role: 'user', data: {_request_id: 'request-a'}},
    {role: 'assistant', content: 'Unrelated answer', data: {_web_message_id: 'other-request', _run_status: 'completed'}},
  ]});
  await f.controller.refresh();
  assert.equal(f.calls.notifications.length, 0);
  assert.equal(f.calls.badge.at(-1), '…');
  assert.equal(f.alarms.size, 1);
});

test('unknown conversation discovery still verifies the request ID before alerting', async () => {
  const f = fixture({preferences: {desktopNotifications: true}});
  f.submit('request-a', null);
  f.setConversation({id: 'conversation-b', run: {message_id: 'different', status: 'completed'}, messages: []});
  await f.controller.refresh();
  assert.equal(f.calls.notifications.length, 0);
  f.setConversation({id: 'conversation-c', run: {message_id: 'request-a', status: 'completed'}, messages: []});
  await f.controller.refresh();
  assert.equal(f.calls.notifications.length, 1);
  await f.browser.notifications.onClicked.emit(f.calls.notifications[0].id);
  assert.equal(f.calls.opened[0].id, 'conversation-c');
});

test('network errors leave work pending without resubmission or false failure', async () => {
  const f = fixture({preferences: {desktopNotifications: true}});
  f.submit();
  f.controller.dispose();
  const controller = setupCompletionSignals(f.browser, {...f.options, readConversation: async () => { throw new Error('Offline'); }});
  await controller.refresh();
  assert.equal(f.calls.notifications.length, 0);
  assert.equal(f.calls.badge.at(-1), '…');
  assert.equal(f.alarms.size, 1);
});

test('server/auth scope changes clear prior unread notifications and prevent cross-session clicks', async () => {
  const f = fixture({preferences: {desktopNotifications: true}});
  f.submit(); f.finish();
  await f.controller.observe();
  const id = f.calls.notifications[0].id;
  f.client.authScope = 'session-b';
  f.client.state.submittedRequests = [];
  f.client.state.settings.serverUrl = 'https://another.example.test';
  await f.controller.observe();
  await f.browser.notifications.onClicked.emit(id);
  assert.equal(f.calls.opened.length, 0);
  assert.equal(f.calls.badge.at(-1), '');
  assert.ok(f.calls.cleared.includes(id));
});

test('logout during a delayed polling response cannot emit its notification', async () => {
  const f = fixture({preferences: {desktopNotifications: true}});
  f.submit();
  f.controller.dispose();
  const controller = setupCompletionSignals(f.browser, {...f.options, readConversation: async () => {
    f.client.intent = false;
    f.client.token = '';
    f.client.authScope = 'logged-out';
    return {id: 'conversation-a', run: {message_id: 'request-a', status: 'completed'}};
  }});
  await controller.refresh();
  assert.equal(f.calls.notifications.length, 0);
  assert.equal(f.calls.badge.at(-1), '');
  assert.equal(f.alarms.size, 0);
});

test('a queued old state snapshot cannot create requests in a new server session', async () => {
  const f = fixture({preferences: {desktopNotifications: true}});
  f.submit(); f.finish();
  const snapshot = structuredClone(f.client.state);
  const observing = f.controller.observe(snapshot);
  f.client.authScope = 'new-session';
  f.client.state.submittedRequests = [];
  await observing;
  assert.equal(f.calls.notifications.length, 0);
  assert.equal(f.data.jarvisCompletionSignals.requests.length, 0);
});

test('permission enablement can attach optional notification listener after initial startup', async () => {
  const f = fixture();
  f.controller.dispose();
  const notifications = f.browser.notifications;
  delete f.browser.notifications;
  const controller = setupCompletionSignals(f.browser, f.options);
  f.browser.notifications = notifications;
  await f.browser.permissions.onAdded.emit({permissions: ['notifications']});
  assert.equal(notifications.onClicked.listeners.size, 1);
  controller.dispose();
});

test('failed conversation opening retains unread state for a later notification click', async () => {
  const f = fixture({preferences: {desktopNotifications: true}});
  f.submit(); f.finish();
  f.controller.dispose();
  const controller = setupCompletionSignals(f.browser, {...f.options, openConversation: async () => { throw new Error('Another request is active'); }});
  await controller.observe();
  await f.browser.notifications.onClicked.emit(f.calls.notifications[0].id);
  assert.equal(f.calls.badge.at(-1), '1');
  assert.equal(f.data.jarvisCompletionSignals.requests[0].unread, true);
});

test('logout while opening a result clears the old notification scope', async () => {
  const f = fixture({preferences: {desktopNotifications: true}});
  f.submit(); f.finish();
  f.controller.dispose();
  const controller = setupCompletionSignals(f.browser, {...f.options, openConversation: async () => {
    f.client.intent = false;
    f.client.token = '';
    f.client.authScope = 'logged-out';
  }});
  await controller.observe();
  await f.browser.notifications.onClicked.emit(f.calls.notifications[0].id);
  assert.equal(f.data.jarvisCompletionSignals.scope, null);
  assert.equal(f.calls.badge.at(-1), '');
});

test('pending requests expire quietly after seven days instead of polling indefinitely', async () => {
  const f = fixture();
  f.submit();
  f.client.state.submittedRequests[0].startedAt = 100000 - 8 * 86400000;
  await f.controller.observe();
  assert.equal(f.calls.badge.at(-1), '');
  assert.equal(f.alarms.size, 0);
  assert.equal(f.data.jarvisCompletionSignals.requests[0].status, 'expired');
});

test('matching active run waits for settlement even if an answer was already persisted', () => {
  assert.equal(conversationOutcome({id: 'conversation-a', run: {message_id: 'request-a', status: 'running'}, messages: [
    {role: 'assistant', content: 'answer', data: {_web_message_id: 'request-a', _run_status: 'completed'}},
  ]}, 'request-a').status, 'pending');
});
