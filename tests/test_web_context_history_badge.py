"""Check recent-history disclosure through the production Web lifecycle hooks."""

from test_web_attachment_bundle_ui import run_browser

SETUP = r"""
const client = new JarvisSocket();
client.connected = true;
client.conversationId = 'thread';
sandbox.window.jarvisSocket = client;
const ui = chat();
ui.tokenCounterEl = new Element();
ui.tokenCountEl = new Element();
ui.tokenCostEl = new Element();
ui._resetTokenCounter = ChatUI.prototype._resetTokenCounter;
ui._resetTokenCounter();
ui.updateHistoryWindow({limit:20});
ui._resolveContextWindowForProviderModel = async () => 1000;
ui.addAssistantMessage = (_text, _tools, data={}) =>
  ui.rememberRenderedMessage('assistant', data.message_id || data._web_message_id);
const history = new Element();
const controls = {historyList:history, conversationFilter:{value:''}};
sandbox.document.getElementById = id => controls[id] || null;
const app = Object.create(JarvisApp.prototype);
Object.assign(app, {
  chat:ui, socket:client, _conversations:[], _archivedExpanded:false,
  _completedResponseIds:new Set(), _cancelStatusTTS(){},
  _updateActiveConversation(){}, _updateConvIdBadge(){},
  _setupHistoryTitleTooltips(){}, _bindConversationHistoryActions(){},
  _filterConversations(){}, _refreshConversationTimes(){}
});
sandbox.window.jarvisApp = app;
function snapshot(messages, id='thread') { return {id, generation:0, messages}; }
function saved(role, id) { return {id, role, content:`Saved ${id}`, data:{}}; }
function summary(count, id='thread') {
  return {id, title:'History fixture', updated_at:'2026-01-02T03:04:05', message_count:count};
}
let summaries = [];
sandbox.fetch = async url => {
  assert.equal(url,'/api/conversations?limit=100&include_archived=true');
  return {ok:true, json:async()=>({ok:true,conversations:summaries})};
};
const finishRefresh = async () => {if (app._historyRefreshPromise) await app._historyRefreshPromise;};
"""


def test_snapshot_reconnect_and_thread_outside_recent_index_keep_canonical_count():
    run_browser(SETUP + r"""
const messages=[saved('user','question'),saved('assistant','answer')];
await app._displayLoadedConversation(snapshot(messages));
await finishRefresh();
assert.equal(ui.historyMessageCount,2);
assert.match(ui.tokenCounterEl.title,/Recent history: up to 2 of 20 saved messages \(you \+ Jarvis\)/);
assert.match(ui.tokenCounterEl.title,/Space before older messages leave the window: 18 messages/);
// A background completion need not have an intervening user message.
messages.push(saved('assistant','late-answer'));
await app._displayLoadedConversation(snapshot(messages),{reconcile:true});
await finishRefresh();
assert.equal(ui.historyMessageCount,3);
assert.match(ui.tokenCounterEl.title,/Recent history: up to 3 of 20/);
assert.equal(client.conversationId,'thread');
// An older active chat can fall outside the existing 100-conversation index.
summaries=Array.from({length:100},(_,index)=>summary(4,`other-${index}`));
await app._displayLoadedConversation(snapshot(Array.from({length:31},(_,index)=>
  saved(index%2?'assistant':'user',`message-${index}`))));
await finishRefresh();
assert.equal(ui.historyMessageCount,31);
assert.match(ui.tokenCounterEl.title,/Older messages outside this window: 11 \(still saved\)/);
await app._loadConversationHistory();
assert.equal(ui.historyMessageCount,31);
assert.equal(client.conversationId,'thread');
""")


def test_index_and_live_lifecycle_refresh_history_without_rebuilding_unchanged_sidebar():
    run_browser(SETUP + r"""
summaries=[summary(20)];
await app._loadConversationHistory();
assert.match(ui.tokenCounterEl.title,/Recent history: up to 20 of 20/);
assert.match(ui.tokenCounterEl.title,/Space before older messages leave the window: 0 messages/);
history.innerHTML += '<span>Keep existing sidebar DOM</span>';
// A rebuild/reset can clear the badge while the sidebar snapshot stays equal.
ui._resetTokenCounter();
await app._loadConversationHistory();
assert.equal(ui.historyMessageCount,20);
assert.match(history.innerHTML,/Keep existing sidebar DOM/);
assert.match(ui.tokenCounterEl.title,/Recent history: up to 20 of 20/);
summaries=[summary(47)];
await app._loadConversationHistory();
assert.match(ui.tokenCounterEl.title,/Recent history: up to 20 of 20/);
assert.match(ui.tokenCounterEl.title,/Older messages outside this window: 27 \(still saved\)/);
assert.doesNotMatch(ui.tokenCounterEl.title,/Space before older/);
app._setupSocketListeners();
let count=47;
for(const event of ['response','runState','conversationsChanged']) {
  summaries=[summary(++count)];
  if (event==='conversationsChanged') {
    const timers=[];
    sandbox.setTimeout=callback=>{timers.push(callback);return timers.length;};
    sandbox.clearTimeout=()=>{};
    client._emit(event,{});
    assert.equal(timers.length,1);
    timers[0]();
  } else {
    client._emit(event,{conversation_id:'thread',message_id:'finished'});
  }
  await finishRefresh();
  assert.equal(ui.historyMessageCount,count);
}
// Late answers already share this index-refresh path; no new wire event is needed.
vm.runInContext(fs.readFileSync(ROOT+'/jarvis-web/client/js/background-tasks.js','utf8'),sandbox);
const jobs=Object.create(sandbox.window.BackgroundTasks.prototype);
Object.assign(jobs,{app,chat:ui,belongs:()=>true,jobs:new Map()});
ui._renderedMessageIds=new Set();
summaries=[summary(++count)];
jobs.continuation({schema_version:1,conversation_id:'thread',continuation_id:'late',
  job_id:'job',message:{content:'Finished result',data:{}}});
await finishRefresh();
assert.equal(ui.historyMessageCount,count);
assert.ok(ui._renderedMessageIds.has('assistant:late'));
""")


def test_settings_refresh_updates_history_limit_without_touching_count_or_usage():
    run_browser(SETUP + r"""
ui.updateHistoryWindow({messageCount:16});
ui._accumulateUsage({input_tokens:120,output_tokens:5,total_tokens:125,
  model_calls:1,peak_context_tokens:125});
let configuredLimit=20;
const urls=[];
sandbox.fetch=async url=>{
  urls.push(url);
  if(url==='/api/settings?mode=local') return {ok:true,json:async()=>({settings:{
    mode:'local',conversation:{history_limit:configuredLimit},
    llm:{provider:{value:'xai'},model:{value:'fixture-context-model'}},
    provider_models:{xai:[{id:'fixture-context-model',context:'1M'}]}
  }})};
  assert.equal(url,'/api/settings/system?mode=local');
  return {ok:true,json:async()=>({config:{}})};
};
await ui.refreshContextWindow('local');
assert.match(ui.tokenCounterEl.title,/Recent history: up to 16 of 20/);
configuredLimit=10;
await ui.refreshContextWindow('local');
assert.equal(ui.historyMessageCount,16);
assert.match(ui.tokenCounterEl.title,/Recent history: up to 10 of 10/);
assert.match(ui.tokenCounterEl.title,/Older messages outside this window: 6 \(still saved\)/);
assert.equal(ui.cumulativeTokens.total,125);
assert.equal(ui.currentContextTokens,125);
assert.deepEqual(urls,['/api/settings?mode=local','/api/settings/system?mode=local',
  '/api/settings?mode=local','/api/settings/system?mode=local']);
""")


def test_new_and_clear_reset_count_but_keep_effective_history_limit():
    run_browser(SETUP + r"""
// The normal settings refresh is covered separately; this checks clearing.
ui.refreshContextWindow=()=>{};
for(const action of ['new','clear']) {
  client.conversationId='thread';
  ui.updateHistoryWindow({messageCount:40,limit:12});
  if(action==='new') {
    app._startNewChat();
    assert.equal(client.conversationId,null);
  } else {
    sandbox.fetch=async url=>{
      if(url==='/api/conversations/thread/clear') return {ok:true,json:async()=>({ok:true})};
      assert.equal(url,'/api/conversations?limit=100&include_archived=true');
      return {ok:true,json:async()=>({ok:true,conversations:[summary(0)]})};
    };
    await app._clearChat();
    await finishRefresh();
    assert.equal(client.conversationId,'thread');
  }
  assert.equal(ui.historyMessageCount,0);
  assert.equal(ui.historyMessageLimit,12);
  ui._renderTokenTooltip();
  assert.match(ui.tokenCounterEl.title,/Recent history: up to 0 of 12/);
  assert.match(ui.tokenCounterEl.title,/Space before older messages leave the window: 12 messages/);
}
""")


PANEL_SETUP = SETUP + r"""
const documentEvents={}, windowEvents={}, viewportEvents={};
sandbox.document.addEventListener=(name,callback,capture)=>documentEvents[name]={callback,capture};
sandbox.window.addEventListener=(name,callback)=>windowEvents[name]=callback;
sandbox.window.innerWidth=800;
sandbox.window.innerHeight=600;
sandbox.window.visualViewport={width:800,height:600,offsetLeft:0,offsetTop:0,
  addEventListener:(name,callback)=>viewportEvents[name]=callback};
ui.tokenDetailsEl=new Element();
ui.tokenDetailsContentEl=new Element();
ui.tokenDetailsEl.hidden=true;
ui.tokenCounterEl.contains=target=>[ui.tokenCounterEl,ui.tokenCountEl,ui.tokenCostEl].includes(target);
ui.tokenDetailsEl.contains=target=>[ui.tokenDetailsEl,ui.tokenDetailsContentEl].includes(target);
ui.tokenCounterEl.getBoundingClientRect=()=>({top:470,bottom:500,right:760});
let focused=0;
ui.tokenCounterEl.focus=()=>focused++;
ui._setupTokenDetails();
"""


def test_badge_panel_real_handlers_keep_hover_live_details_and_reset_consistent():
    run_browser(PANEL_SETUP + r"""
ui.updateHistoryWindow({messageCount:18});
const initial=ui.tokenCounterEl.title;
ui.tokenCounterEl.click();
assert.equal(ui.tokenDetailsEl.hidden,false);
assert.equal(ui.tokenCounterEl['aria-expanded'],'true');
assert.equal(ui.tokenCounterEl.title,'');
assert.equal(ui.tokenDetailsContentEl.textContent,initial);
for(const target of [ui.tokenCountEl,ui.tokenDetailsContentEl]) {
  documentEvents.pointerdown.callback({target});
  assert.equal(ui.tokenDetailsEl.hidden,false);
}
await ui._updateTokenCounter({input_tokens:123,output_tokens:7,total_tokens:130,
  model_calls:1,peak_context_tokens:130});
ui.updateHistoryWindow({messageCount:23});
assert.match(ui.tokenDetailsContentEl.textContent,/Chat processed: 130 tokens/);
assert.match(ui.tokenDetailsContentEl.textContent,/Older messages outside this window: 3/);
assert.equal(ui.tokenCounterEl.title,'');
// Other key handlers retain control unless this disclosure consumes Escape.
documentEvents.keydown.callback({key:'Enter',preventDefault(){assert.fail('consumed Enter');}});
assert.equal(ui.tokenDetailsEl.hidden,false);
let prevented=0, stopped=0;
assert.equal(documentEvents.keydown.capture,true);
documentEvents.keydown.callback({key:'Escape',preventDefault(){prevented++;},stopPropagation(){stopped++;}});
assert.equal(prevented,1);
assert.equal(stopped,1);
assert.equal(focused,1);
assert.equal(ui.tokenDetailsEl.hidden,true);
assert.equal(ui.tokenCounterEl['aria-expanded'],'false');
assert.equal(ui.tokenCounterEl.title,ui.tokenDetailsContentEl.textContent);
ui.tokenCounterEl.click();
documentEvents.pointerdown.callback({target:new Element()});
assert.equal(ui.tokenDetailsEl.hidden,true);
ui.tokenCounterEl.click();
ui.tokenCounterEl.click();
assert.equal(ui.tokenDetailsEl.hidden,true);
for(const resize of [windowEvents.resize,viewportEvents.resize]) {
  ui.tokenCounterEl.click();
  resize();
  assert.equal(ui.tokenDetailsEl.hidden,true);
}
ui.tokenCounterEl.click();
ui._resetTokenCounter();
assert.equal(ui.tokenDetailsEl.hidden,true);
assert.equal(ui.tokenCounterEl['aria-expanded'],'false');
assert.equal(ui.tokenDetailsContentEl.textContent,'');
assert.equal(ui.tokenCounterEl.title,'');
assert.equal(ui.historyMessageCount,0);
assert.equal(ui.historyMessageLimit,20);
""")


def test_panel_geometry_keeps_scrollable_content_inside_layout_and_visual_viewports():
    run_browser(PANEL_SETUP + r"""
function assertVisibleBounds() {
  const viewport=sandbox.window.visualViewport;
  const style=ui.tokenDetailsEl.style;
  const width=parseFloat(style.width),height=parseFloat(style.maxHeight);
  const left=parseFloat(style.left);
  const top=style.top==='auto'
    ? sandbox.window.innerHeight-parseFloat(style.bottom)-height
    : parseFloat(style.top);
  assert.ok(Number.isFinite(width)&&width>0&&width<=420);
  assert.ok(height>=0);
  assert.ok(left>=viewport.offsetLeft+12);
  assert.ok(left+width<=viewport.offsetLeft+viewport.width-12);
  assert.ok(top>=viewport.offsetTop+12);
  assert.ok(top+height<=viewport.offsetTop+viewport.height-12);
}
// Desktop: enough room above the bottom-right context badge.
ui._positionTokenDetails();
assert.equal(ui.tokenDetailsEl.style.top,'auto');
assertVisibleBounds();
// Mobile keyboard/pinch viewport: an anchor above the visual viewport must
// open below it and still fit the visible width.
Object.assign(sandbox.window.visualViewport,{width:320,height:380,offsetLeft:17,offsetTop:150});
ui.tokenCounterEl.getBoundingClientRect=()=>({top:20,bottom:50,right:900});
ui._positionTokenDetails();
assert.equal(ui.tokenDetailsEl.style.bottom,'auto');
assertVisibleBounds();
// A badge below the visual viewport is clamped back into available space.
ui.tokenCounterEl.getBoundingClientRect=()=>({top:900,bottom:930,right:-20});
ui._positionTokenDetails();
assert.equal(ui.tokenDetailsEl.style.top,'auto');
assertVisibleBounds();
""")
