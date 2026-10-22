const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');
class Element {
  constructor() {
    this.textContent = ''; this.value = ''; this.checked = false; this.disabled = false;
    this.children = []; this.events = {}; this.attributes = {}; this.active = false;
    this.classList = {contains: () => this.active};
  }
  addEventListener(name, handler) { this.events[name] = handler; }
  setAttribute(name, value) { this.attributes[name] = value; }
  toggleAttribute(name, enabled) { this[name] = enabled; }
  appendChild(child) { this.children.push(child); }
  replaceChildren() { this.children = []; }
  set innerHTML(_) { throw new Error('Notification content must use textContent'); }
}
const categories = ['alerts', 'reminders', 'background_tasks', 'notifications'];
const channels = {ok: true, configured: true, editable: true, enabled: true,
  configuration: 'enabled', categories: {alerts: true, reminders: true, background_tasks: false, notifications: true}};
const answer = data => ({ok: true, status: 200, json: async () => data});
function setup(storage = new Map()) {
  const ids = ['settingsModal', 'settings-notifications', 'notifications-enabled',
    'notification-category-controls', 'notification-history-list', 'notification-channel-controls',
    'notification-channels-result', 'notification-history-status', 'notification-history-page',
    'notificationsPreviousBtn', 'notificationsNextBtn', 'refreshNotificationsBtn',
    ...categories.map(name => `notifications-category-${name}`),
    ...['mode', 'source', 'channel', 'state'].map(name => `notification-history-${name}`)];
  const elements = Object.fromEntries(ids.map(id => [id, new Element()]));
  const calls = [], pending = [];
  const sandbox = {window: {}, console, URL, URLSearchParams, AbortSignal,
    localStorage: {getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value)},
    document: {getElementById: id => elements[id], createElement: () => new Element(), createTextNode: text => ({textContent: text})},
    Utils: {auth: {fetch(url, options) {
      calls.push({url, options});
      assert.ok(options.signal, 'Every request must have a bounded timeout');
      return new Promise((resolve, reject) => pending.push({resolve, reject}));
    }}}};
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(root + '/jarvis-web/client/js/notifications.js', 'utf8'), sandbox);
  const component = new sandbox.window.NotificationsSettings({socket: {mode: 'cloud'}});
  const show = () => { elements.settingsModal.active = elements['settings-notifications'].active = true; };
  return {component, elements, calls, pending, show, storage};
}

test('opening notifications is lazy and cannot publish', async () => {
  const {component, elements, calls, pending, show} = setup();
  await component.refresh(); assert.equal(calls.length, 0);
  show(); const refresh = component.refresh();
  assert.deepEqual(calls.map(call => call.url), ['/api/notifications/channels', '/api/notifications?limit=25&offset=0&mode=cloud']);
  assert.ok(calls.every(call => !call.options.method));
  pending.shift().resolve(answer(channels));
  pending.shift().resolve(answer({ok: true, items: [], total: 0})); await refresh;
  assert.equal(elements['notifications-enabled'].disabled, false);
  assert.equal(elements['notifications-category-background_tasks'].checked, false);
  assert.match(elements['notification-history-status'].textContent, /No notifications/);
  assert.equal(elements.notificationsNextBtn.disabled, true);
  assert.ok(!calls.some(call => call.url.includes('/test')));
});

test('first opening uses restored app mode while persisted and deliberate history modes remain stable', async () => {
  const state = setup();
  state.component.app.socket.mode = 'local';
  state.show();
  let refresh = state.component.refresh();
  assert.match(state.calls[1].url, /mode=local/);
  state.pending.shift().resolve(answer(channels));
  state.pending.shift().resolve(answer({ok: true, items: [], total: 0})); await refresh;
  state.component.app.socket.mode = 'cloud';
  let history = state.component.loadHistory();
  assert.match(state.calls.at(-1).url, /mode=local/);
  state.pending.shift().resolve(answer({ok: true, items: [], total: 0})); await history;

  const saved = setup(new Map([['jarvis_notification_filters', JSON.stringify({mode: 'cloud'})]]));
  saved.component.app.socket.mode = 'local'; saved.show();
  refresh = saved.component.refresh();
  assert.match(saved.calls[1].url, /mode=cloud/);
  saved.pending.shift().resolve(answer(channels));
  saved.pending.shift().resolve(answer({ok: true, items: [], total: 0})); await refresh;
  saved.elements['notification-history-mode'].value = 'local';
  saved.elements['notification-history-mode'].events.change();
  assert.match(saved.calls.at(-1).url, /mode=local/);
  saved.pending.shift().resolve(answer({ok: true, items: [], total: 0}));
  await new Promise(resolve => setImmediate(resolve));
  history = saved.component.loadHistory();
  assert.match(saved.calls.at(-1).url, /mode=local/);
  saved.pending.shift().resolve(answer({ok: true, items: [], total: 0})); await history;
});

test('switches save immediately and reload persisted server settings', async () => {
  const {component, elements, calls, pending, show} = setup(); show();
  const load = component.loadChannels(); pending.shift().resolve(answer(channels)); await load;
  const changed = {...channels, categories: {...channels.categories, notifications: false}};
  elements['notifications-category-notifications'].checked = false;
  const save = component.saveChannels({categories: {notifications: false}});
  assert.equal(elements['notifications-enabled'].disabled, true);
  assert.equal(calls.at(-1).options.method, 'PATCH');
  assert.deepEqual(JSON.parse(calls.at(-1).options.body), {categories: {notifications: false}});
  pending.shift().resolve(answer(changed)); await save;
  assert.equal(elements['notifications-category-notifications'].checked, false);
  const reload = component.loadChannels(); pending.shift().resolve(answer(changed)); await reload;
  assert.equal(elements['notifications-category-notifications'].checked, false);
  const failed = component.saveChannels({enabled: false});
  pending.shift().reject(new Error('private credential')); await failed;
  assert.equal(elements['notifications-enabled'].checked, true);
  assert.ok(!elements['notification-channels-result'].textContent.includes('credential'));
  assert.ok(calls.every(call => call.url === '/api/notifications/channels'));
});

test('disabled or missing settings reject programmatic toggle attempts', async () => {
  const {component, elements, calls, pending, show} = setup(); show();
  let load = component.loadChannels(); pending.shift().resolve(answer({...channels, enabled: false})); await load;
  assert.equal(elements['notifications-enabled'].disabled, false);
  assert.equal(elements['notifications-category-alerts'].disabled, true);
  load = component.loadChannels(); pending.shift().resolve(answer({ok: true, editable: false, configured: false})); await load;
  assert.equal(elements['notifications-enabled'].disabled, true);
  await component.saveChannels({enabled: true}); assert.equal(calls.length, 2);
});

test('history safely renders old rows, bodies and pending failure receipts', async () => {
  const {component, elements, pending, show} = setup(); show();
  const load = component.loadHistory();
  pending.shift().resolve(answer({ok: true, total: 2, items: [
    {title: '<img src=x onerror=alert(1)>', message: '<script>unsafe()</script>', source_type: 'notifications',
      source: 'watch', created_at: '2026-10-22T20:00:00Z', deliveries: [{channel: 'ntfy', state: 'pending', error: '<private>'}]},
    {source_type: 'alerts', source: 'alerts', created_at: null, deliveries: []}
  ]})); await load;
  const [first, old] = elements['notification-history-list'].children;
  assert.equal(first.children[0].textContent, '<img src=x onerror=alert(1)>');
  assert.equal(first.children[2].textContent, '<script>unsafe()</script>');
  assert.match(first.children[3].textContent, /ntfy: pending/);
  assert.equal(old.children[0].textContent, 'Alerts');
  assert.match(old.children[1].textContent, /Time unavailable/);
  assert.equal(old.children.at(-1).textContent, 'Saved locally');
});

test('filters persist and stale responses cannot overwrite a newer filtered page', async () => {
  const state = setup(); const {component, elements, calls, pending, show, storage} = state; show();
  const old = component.loadHistory();
  elements['notification-history-source'].value = 'notifications';
  elements['notification-history-mode'].value = 'local';
  component.saveFilters();
  const newer = component.loadHistory();
  const stale = pending.shift();
  pending.shift().resolve(answer({ok: true, items: [{title: 'Local result', deliveries: []}], total: 30})); await newer;
  stale.reject(new Error('private')); await old;
  assert.equal(elements['notification-history-list'].children[0].children[0].textContent, 'Local result');
  assert.match(calls.at(-1).url, /mode=local&source_type=notifications/);
  assert.equal(elements.notificationsNextBtn.disabled, false);
  const restored = setup(storage);
  assert.equal(restored.elements['notification-history-source'].value, 'notifications');
  assert.equal(restored.elements['notification-history-mode'].value, 'local');
  component.offset = 25;
  const page = component.loadHistory();
  pending.shift().resolve(answer({ok: true, items: [{title: 'Page two', deliveries: []}], total: 30})); await page;
  assert.match(calls.at(-1).url, /offset=25/);
  assert.equal(elements.notificationsPreviousBtn.disabled, false);
  assert.equal(elements.notificationsNextBtn.disabled, true);
});

test('history errors clear stale rows, expose no raw error and recover on refresh', async () => {
  const {component, elements, pending, show} = setup(); show();
  let load = component.loadHistory(); pending.shift().reject(new Error('private token')); await load;
  assert.equal(elements['notification-history-list'].children.length, 0);
  assert.match(elements['notification-history-status'].textContent, /unavailable/);
  assert.ok(!elements['notification-history-status'].textContent.includes('token'));
  load = component.loadHistory(); pending.shift().resolve(answer({ok: true, items: [], total: 0})); await load;
  assert.match(elements['notification-history-status'].textContent, /No notifications/);
});

test('legacy delivery time and source links retain mode without inventing an item route', async () => {
  const {component, elements, pending, show} = setup(); show();
  const load = component.loadHistory();
  pending.shift().resolve(answer({ok: true, total: 1, items: [
    {source_type: 'alerts', source: 'alerts', source_id: '42', mode: 'local',
      created_at: null, deliveries: [{channel: 'ntfy', state: 'delivered', sent_at: '2026-10-22T20:00:00Z'}]}
  ]})); await load;
  const row = elements['notification-history-list'].children[0];
  assert.match(row.children[1].textContent, /Accepted/);
  assert.match(row.children[2].textContent, /accepted by service/);
  assert.equal(row.children[3].textContent, 'Source reference: 42');
  const link = row.children[3].children.at(-1);
  assert.equal(link.href, 'http://localhost:5002/?mode=local#alerts');
  assert.equal(link.rel, 'noopener noreferrer');
  assert.equal(component.sourceLink({source_type: 'background_tasks'}), null);
});
