"""Execute sidebar push/coalescing against the shipped browser classes."""
from test_web_attachment_bundle_ui import run_browser


SETUP = r"""
const wireHandlers = {}, outbound = [];
const client = new JarvisSocket();
client.connected = true;
client.conversationId = 'active';
client.pendingRequestId = 'live-request';
client.socket = {on: (name, fn) => wireHandlers[name] = fn,
  emit: (...args) => outbound.push(args)};
client._setupEventHandlers();
const ui = chat();
ui.inputField.value = 'Unsent follow-up';
ui.isProcessing = true;
ui.currentMessageId = 'live-request';
ui.attachedDocuments = [file('draft.pdf')];
const history = new Element();
history.scrollTop = 245;
const filter = {value: 'Saturn'};
sandbox.document.getElementById = id => ({historyList:history, conversationFilter:filter}[id] || null);
sandbox.document.activeElement = ui.inputField;
sandbox.window.matchMedia = () => ({matches:false});
const app = Object.create(JarvisApp.prototype);
Object.assign(app, {socket:client, chat:ui, _conversations:[], _archivedExpanded:true});
app._setupSocketListeners();
function snapshot(conversations) { return {json:async()=>({ok:true,conversations})}; }
const active = {id:'active',title:'Saturn study',updated_at:'2026-09-18T10:00:00',message_count:2};
const other = {id:'mobile',title:'New from mobile',updated_at:'2026-09-18T11:00:00',message_count:1};
const tick = () => new Promise(resolve => setImmediate(resolve));
"""


def test_push_bursts_refresh_only_sidebar_preserving_live_chat_and_filter():
    run_browser(SETUP + r"""
const timers = new Map(); let nextTimer = 1;
sandbox.setTimeout = (fn, delay) => {assert.equal(delay,150); const id=nextTimer++; timers.set(id,fn); return id;};
sandbox.clearTimeout = id => timers.delete(id);
const rows = [active,other].map(conv => ({style:{},querySelector:()=>({textContent:conv.title})}));
history.querySelectorAll = selector => selector==='.history-item' ? rows : [];
let reads = 0;
sandbox.fetch = async url => {assert.equal(url,'/api/conversations?limit=100&include_archived=true'); reads++; return snapshot([other,active]);};
for (let i=0;i<20;i++) wireHandlers['conversations:changed']({});
assert.equal(timers.size,1);
const fire = [...timers.values()][0]; timers.clear(); fire();
await app._historyRefreshPromise;
assert.equal(reads,1);
assert.equal(timers.size,0); // No repeating poll scheduled after the update.
assert.match(history.innerHTML,/New from mobile/);
assert.match(history.innerHTML,/history-item active/);
assert.equal(rows[0].style.display,'');
assert.equal(rows[1].style.display,'none');
assert.equal(history.scrollTop,245);
assert.equal(filter.value,'Saturn');
assert.equal(app._archivedExpanded,true);
assert.equal(client.conversationId,'active');
assert.equal(client.pendingRequestId,'live-request');
assert.equal(ui.inputField.value,'Unsent follow-up');
assert.equal(sandbox.document.activeElement,ui.inputField);
assert.equal(ui.isProcessing,true);
assert.equal(ui.currentMessageId,'live-request');
assert.equal(ui.attachedDocuments[0].name,'draft.pdf');
assert.deepEqual(outbound,[]); // No load, resume, cancel, mode or tool event.
""")


def test_change_during_fetch_gets_one_followup_without_parallel_or_stale_overwrite():
    run_browser(SETUP + r"""
const first = deferred(), second = deferred();
let reads=0;
sandbox.fetch = () => (++reads===1 ? first.promise : second.promise);
const loading = app._loadConversationHistory();
for(let i=0;i<15;i++) wireHandlers['conversations:changed']({});
const alsoLoading = app._loadConversationHistory();
assert.equal(reads,1);
first.resolve(snapshot([active]));
await tick();
assert.equal(reads,2);
second.resolve(snapshot([other,active]));
await Promise.all([loading,alsoLoading]);
assert.equal(reads,2);
assert.deepEqual(Array.from(app._conversations,conv=>conv.id),['mobile','active']);
assert.match(history.innerHTML,/New from mobile/);
assert.equal(app._historyRefreshPromise,null);
""")


def test_same_snapshot_keeps_dom_and_transient_error_keeps_last_good_list():
    run_browser(SETUP + r"""
sandbox.fetch = async () => snapshot([active]);
await app._loadConversationHistory();
history.innerHTML += '<span>Existing DOM identity marker</span>';
await app._loadConversationHistory();
assert.match(history.innerHTML,/Existing DOM identity marker/);
sandbox.fetch = async () => {throw new Error('Temporary disconnection');};
await app._loadConversationHistory();
assert.match(history.innerHTML,/Existing DOM identity marker/);
sandbox.fetch = async () => snapshot([other,active]);
await app._loadConversationHistory();
assert.match(history.innerHTML,/New from mobile/);
assert.doesNotMatch(history.innerHTML,/Existing DOM identity marker/);
""")


def test_refresh_preserves_open_conversation_menu():
    run_browser(SETUP + r"""
history.querySelector = selector => selector==='.history-menu-dropdown.open' ? {dataset:{convId:'active'}} : null;
const restored = [];
app.toggleConversationMenu = id => restored.push(id);
sandbox.fetch = async () => snapshot([other,active]);
await app._loadConversationHistory();
assert.deepEqual(restored,['active']);
assert.equal(client.conversationId,'active');
""")


def test_push_does_not_reopen_archives_collapsed_by_the_user():
    run_browser(SETUP + r"""
active.archived = true;
sandbox.fetch = async () => snapshot([active]);
await app._loadConversationHistory();
assert.equal(app._archivedExpanded,true);
app._archivedExpanded = false;
sandbox.fetch = async () => snapshot([other,active]);
await app._loadConversationHistory();
assert.equal(app._archivedExpanded,false);
assert.match(history.innerHTML,/history-archived-list" style="display: none/);
""")


CLOCK_SETUP = SETUP + r"""
let clock = Date.parse(active.updated_at) + 30_000;
sandbox.Date = class extends Date {
  constructor(...args) { super(...(args.length ? args : [clock])); }
  static now() { return clock; }
};
let reads = 0;
sandbox.fetch = async () => { reads++; return snapshot([active]); };
await app._loadConversationHistory();
const dateLabel = {textContent: history.innerHTML.match(/class="history-date">([^<]+)/)[1]};
const row = {dataset:{convId:active.id},querySelector:selector=>selector==='.history-date' ? dateLabel : null};
history.querySelectorAll = selector => selector==='.history-item' ? [row] : [];
const originalDOM = history.innerHTML;
assert.equal(dateLabel.textContent,'Just now · 2 messages');
"""


def test_unchanged_snapshot_updates_relative_time_without_rebuilding_sidebar():
    run_browser(CLOCK_SETUP + r"""
clock += 10 * 60_000;
await app._loadConversationHistory();
assert.equal(dateLabel.textContent,'10m ago · 2 messages');
assert.equal(history.innerHTML,originalDOM);
assert.equal(history.scrollTop,245);
assert.equal(filter.value,'Saturn');
assert.equal(reads,2);
assert.deepEqual(outbound,[]);
""")


def test_local_clock_updates_visible_labels_and_catches_up_after_hidden_tab_without_fetch():
    run_browser(CLOCK_SETUP + r"""
const intervals = [], listeners = [];
sandbox.setInterval = (callback,delay) => { intervals.push({callback,delay}); return intervals.length; };
sandbox.document.addEventListener = (event,callback) => listeners.push({event,callback});
app._startConversationClock();
app._startConversationClock();
assert.equal(intervals.length,1);
assert.equal(intervals[0].delay,60_000);
assert.equal(listeners.length,1);
assert.equal(listeners[0].event,'visibilitychange');
clock += 60_000;
intervals[0].callback();
assert.equal(dateLabel.textContent,'1m ago · 2 messages');
sandbox.document.hidden = true;
clock += 2 * 60 * 60_000;
intervals[0].callback();
listeners[0].callback();
assert.equal(dateLabel.textContent,'1m ago · 2 messages');
sandbox.document.hidden = false;
listeners[0].callback();
assert.equal(dateLabel.textContent,'2h ago · 2 messages');
assert.equal(reads,1);
assert.equal(history.innerHTML,originalDOM);
assert.equal(history.scrollTop,245);
assert.equal(client.conversationId,'active');
assert.equal(ui.inputField.value,'Unsent follow-up');
assert.equal(ui.isProcessing,true);
assert.deepEqual(outbound,[]);
""")
