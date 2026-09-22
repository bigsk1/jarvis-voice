"""Run the production browser reconciliation and event dispatch in a Node VM."""
import pytest
from test_web_attachment_bundle_ui import run_browser

SETUP = r"""
const storage = new Map();
sandbox.window.sessionStorage = {
  getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value),
  removeItem: key => storage.delete(key)
};
const client = new JarvisSocket();
client.connected = true;
client.conversationId = 'thread';
sandbox.window.jarvisSocket = client;
const ui = chat(), rendered = [], played = [], loaded = [];
ui._resetProcessingUi = ChatUI.prototype._resetProcessingUi;
ui.addAssistantMessage = (text, tools, data = {}) => {
  rendered.push(text);
  ui.rememberRenderedMessage('assistant', data.message_id || data._web_message_id);
};
ui.addErrorMessage = text => rendered.push('ERROR: ' + text);
ui._activatePendingToolsForMessage = () => {};
ui._clearMessageResponseActions = () => {};
ui._clearPendingToolsForMessage = () => {};
ui._setupSocketListeners();
const app = Object.create(JarvisApp.prototype);
Object.assign(app, {
  chat: ui, socket: client, audioEnabled: true, _completedResponseIds: new Set(),
  _updateActiveConversation(){}, _updateConvIdBadge(){}, _loadConversationHistory(){},
  _cancelStatusTTS(){}, _generateAndPlayTTS: text => played.push(text),
  _playAudio: url => played.push(url)
});
app._setupSocketListeners();
sandbox.window.jarvisApp = app;
"""


def test_reloading_keeps_per_tab_conversation_and_explicit_new_chat_clears_it():
    run_browser(SETUP + r"""
assert.equal(new JarvisSocket().conversationId, 'thread');
client.conversationId = null;
assert.equal(new JarvisSocket().conversationId, null);
""")


@pytest.mark.parametrize('ready_first', [True, False])
@pytest.mark.parametrize('first_request', [True, False])
def test_socket_handshake_restores_history_or_first_receipt(ready_first, first_request):
    run_browser(SETUP + f"\nconst readyFirst={str(ready_first).lower()}, firstRequest={str(first_request).lower()};\n" + r"""
// Use the shipped client: onconnect drains buffered custom events BEFORE
// emitting its public connect event. No transport or server is started.
const io = require(ROOT + '/jarvis-web/client/vendor/socket.io.min.js');
const manager = new io.Manager('http://127.0.0.1:1', {autoConnect:false,reconnection:false});
const wire = manager.socket('/'), packets=[];
manager._packet=packet=>packets.push(packet);
client.connected=false;
client.socket=wire;
if (firstRequest) {
  client.conversationId=null;
  client.pendingRequestId='accepted';
}
sandbox.document.getElementById=()=>null;
Object.assign(app,{statusText:{},_toolSyncWarningTimer:1,
  _updateConnectionStatus(){},_checkToolSyncWarning(){},_consumeMediaHandoff(){}});
client._setupEventHandlers();
const ready={nsp:'/',data:['connected',{session_id:'new-socket',mode:'cloud'}]};
if (readyFirst) wire.onevent(ready);
wire.onconnect('new-socket');
if (!readyFirst) wire.onevent(ready);
assert.equal(client.connected,true);
assert.equal(packets.length,2);
assert.equal(packets[0].data[0],firstRequest?'chat:resume':'conversation:load');
assert.equal(packets[1].data[0],'conversations:subscribe');
assert.equal(ui._conversationLoadPending,true);
if (!firstRequest) assert.equal(packets[0].data[1].reconnect_only,false);
wire.onevent({nsp:'/',data:['conversation:loaded',{conversation:{id:'thread',messages:[
  {role:'user',content:'Saved question',data:{_request_id:'accepted'}},
  {role:'assistant',content:'Saved answer',data:{_web_message_id:'accepted'}}
]}}]});
assert.deepEqual(rendered,['Saved answer']);
assert.deepEqual(played,[]);
assert.equal(ui._conversationLoadPending,false);
assert.equal(client.pendingRequestId,null);
assert.equal(client.conversationId,'thread');
assert.equal(notices.some(item=>String(item[0]).includes('Connect to Jarvis')),false);
""")


def test_first_request_identity_survives_reload_until_acceptance_is_confirmed():
    run_browser(SETUP + r"""
client.conversationId = null;
client.socket = {emit(){}};
client.sendMessage('Recover the first request');
const reloaded = new JarvisSocket();
assert.equal(reloaded.pendingRequestId, client.lastRequestId);
assert.equal(reloaded.conversationId, null);
client.clearPendingRequest();
assert.equal(new JarvisSocket().pendingRequestId, null);
""")


def test_reconnect_after_lost_first_receipt_accepts_recovered_conversation():
    run_browser(SETUP + r"""
client.conversationId=null;
client.pendingRequestId='accepted';
const emissions=[];
client.socket={emit:(event,data)=>emissions.push([event,data])};
sandbox.document.getElementById=()=>null;
Object.assign(app,{_requestedConversationId:null,statusText:{},_toolSyncWarningTimer:1,
  _updateConnectionStatus(){},_checkToolSyncWarning(){},_consumeMediaHandoff(){}});
client._emit('sessionReady',{mode:'cloud'});
assert.equal(emissions[0][0],'chat:resume');
assert.equal(ui._conversationLoadPending,true);
await app._displayLoadedConversation({id:'recovered',messages:[
  {role:'user',content:'First request',data:{_request_id:'accepted'}}
]});
assert.equal(client.conversationId,'recovered');
assert.equal(ui._conversationLoadPending,false);
""")


def test_snapshot_restores_live_manual_review_controls():
    run_browser(SETUP + r"""
const guards=[];
ui.addAssistantMessage=(text, tools, data) => guards.push(data.completion_guard);
await app._displayLoadedConversation({id:'thread',messages:[
  {role:'assistant',content:'Review this',data:{_web_message_id:'answer'}}
],completion_guards:{answer:{prompt_user:true,mode:'manual',expires_in_ms:60000}}});
assert.equal(guards[0].prompt_user,true);
assert.equal(guards[0].expires_in_ms,60000);
""")


def test_slow_snapshot_metadata_cannot_overwrite_a_newer_conversation():
    run_browser(SETUP + r"""
let resolve;
ui.tokenCounterEl={style:{}};
ui._resolveContextWindowForProviderModel=()=>new Promise(done => {resolve=done});
const restoring=ui.restoreTokenCounter({input:10,output:5,total:15},0,false,false,
  {provider:'ollama',model:'old',mode:'local'});
const newer={provider:'openai',model:'new',mode:'cloud',contextWindow:100};
ui.tokenStatsMeta=newer;
resolve(999);
await restoring;
assert.equal(ui.tokenStatsMeta,newer);
assert.equal(ui.tokenStatsMeta.contextWindow,100);
""")


def test_snapshot_restores_stop_and_stopping_waits_for_real_completion():
    run_browser(SETUP + r"""
await app._displayLoadedConversation({id:'thread', messages:[{role:'user', content:'Research'}],
  run:{message_id:'run-1', conversation_id:'thread', status:'running', mode:'local', kind:'chat', status_text:'Searching'}});
assert.equal(ui.isProcessing, true);
assert.equal(ui.currentMessageId, 'run-1');
assert.equal(ui.sendBtn.disabled, true);
assert.equal(ui.stopBtn.disabled, false);
const sent=[];
client.socket={emit:(name, data)=>sent.push([name,data])};
ui.cancelProcessing();
assert.equal(sent[0][0], 'chat:cancel');
assert.equal(sent[0][1].conversation_id, 'thread');
assert.equal(sent[0][1].message_id, 'run-1');
client._emit('cancelAck',{message_id:'run-1',conversation_id:'thread',status:'stopping'});
assert.equal(ui.isProcessing,true);
assert.equal(ui.sendBtn.disabled,true);
assert.equal(ui.currentMessageId,'run-1');
client._emit('runState',{message_id:'run-1',conversation_id:'thread',status:'cancelled'});
assert.equal(ui.isProcessing,false);
assert.equal(ui.currentMessageId,null);
""")


def test_missed_result_is_rendered_once_and_not_spoken_on_reconnect():
    run_browser(SETUP + r"""
await app._displayLoadedConversation({id:'thread', messages:[
  {role:'user',content:'Research'},
  {role:'assistant',content:'Saved result',data:{_web_message_id:'run-1'}}
], run:{message_id:'run-1',conversation_id:'thread',status:'completed',kind:'chat'}});
assert.deepEqual(rendered,['Saved result']);
assert.equal(ui.isProcessing,false);
client._emit('response',{message_id:'run-1',conversation_id:'thread',text:'Saved result',speech:'Saved result'});
client._emit('status',{message_id:'run-1',conversation_id:'thread',status:'Late progress'});
client._emit('error',{message_id:'run-1',conversation_id:'thread',error:'Late failure'});
assert.deepEqual(rendered,['Saved result']);
assert.deepEqual(played,[]);
""")


def test_old_conversation_events_cannot_change_new_chat_or_play_audio():
    run_browser(SETUP + r"""
client.conversationId = 'other';
for (const event of ['thinking','toolStart','toolProgress','toolError','response','error','runState','status']) {
  client._emit(event,{message_id:'old',conversation_id:'thread',text:'Wrong chat',speech:'Wrong chat',
    error:'Wrong chat',status:'running'});
}
assert.equal(ui.isProcessing,false);
assert.deepEqual(rendered,[]);
assert.deepEqual(played,[]);
client.conversationId=null;
client._emit('response',{conversation_id:'other',message_id:'old2',text:'Wrong chat'});
assert.deepEqual(rendered,[]);
""")


def test_failed_navigation_unlocks_loading_without_interrupting_displayed_task():
    run_browser(SETUP + r"""
ui.restoreRunState({conversation_id:'thread',message_id:'active',status:'running'}, {fromSnapshot:true});
client.socket={emit(){}};
app.loadConversation('missing');
client._emit('error',{conversation_id:'missing',error:'Conversation not found'});
assert.equal(ui._conversationLoadPending,false);
assert.equal(app._pendingConversationLoad,null);
assert.equal(client.conversationId,'thread');
assert.equal(ui.isProcessing,true);
assert.equal(ui.currentMessageId,'active');
assert.deepEqual(rendered,[]);
assert.equal(notices.at(-1)[0],'Conversation not found');
""")


def test_rejected_send_restores_sources_hints_and_both_drafts():
    run_browser(SETUP + r"""
app.loadConversation = cid => loaded.push(cid);
ui._pendingSend={requestId:'rejected',text:'Original draft',documents:[],images:[],
  imageAction:'analyze',imageSettings:{},toolHints:['get_time']};
ui.inputField.value='Newly typed thought';
client._emit('rejected',{conversation_id:'thread',message_id:'rejected',error:'Already running'});
assert.match(ui.inputField.value,/Original draft/);
assert.match(ui.inputField.value,/Newly typed thought/);
assert.equal(ui.selectedToolHints[0],'get_time');
assert.deepEqual(loaded,['thread']);
assert.equal(ui._pendingSend,null);
""")


def test_other_tab_start_loads_the_user_turn_without_resending():
    run_browser(SETUP + r"""
app.loadConversation = cid => loaded.push(cid);
client._emit('runState',{conversation_id:'thread',message_id:'remote',status:'running'});
assert.deepEqual(loaded,['thread']);
assert.deepEqual(sent,[]);
""")


def test_interrupted_history_explains_uncertain_actions_without_automatic_retry():
    run_browser(SETUP + r"""
const error='Server restarted; not retried. Some actions may have completed.';
const run={conversation_id:'thread',message_id:'r',status:'interrupted',kind:'chat',error};
await app._displayLoadedConversation({id:'thread',run,messages:[
  {role:'user',content:'Do the work',data:{_run:run,_request_id:'r'}}
]});
assert.deepEqual(rendered,['ERROR: '+error]);
assert.equal(ui.isProcessing,false);
assert.deepEqual(sent,[]);
assert.deepEqual(played,[]);
""")


def test_completed_parent_guard_event_cannot_unlock_a_new_task():
    run_browser(SETUP + r"""
ui.restoreRunState({conversation_id:'thread',message_id:'new',status:'running'}, {fromSnapshot:true});
ui._updateCompletionGuardCard=()=>{};
client._emit('completionGuardTicketCreated',{message_id:'old',status:'ticket_created'});
app.modeSelect={disabled:true};
client._emit('runState',{conversation_id:'thread',message_id:'old',status:'completed'});
assert.equal(ui._serverRunState.message_id,'new');
assert.equal(app.modeSelect.disabled,true);
assert.equal(ui.isProcessing,true);
assert.equal(ui.currentMessageId,'new');
""")


def test_request_ids_and_stop_work_without_secure_context_random_uuid():
    run_browser(SETUP + r"""
sandbox.crypto = {getRandomValues: require('node:crypto').webcrypto.getRandomValues.bind(require('node:crypto').webcrypto)};
const outgoing=[];
client.socket={emit:(name,data)=>outgoing.push([name,data])};
client.sendMessage('Local LAN request');
assert.match(outgoing[0][1].request_id,/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
assert.equal(client.lastRequestId,outgoing[0][1].request_id);
client.connected=false;
assert.equal(client.cancel('thread',client.lastRequestId),false);
assert.equal(outgoing.length,1);
""")


@pytest.mark.parametrize('kind', ['pdf', 'audio', 'image'])
def test_socket_reconnect_does_not_abort_attachment_preparation(kind):
    run_browser(SETUP + f"const kind={kind!r};\n" + r"""
const uploads=deferred(), entered=deferred(), outgoing=[];
client.socket={emit:(event,data)=>outgoing.push([event,data])};
sandbox.document.getElementById=()=>null;
Object.assign(app,{_sessionReadyOnce:true,_displayedConversationId:'thread',statusText:{},
  _toolSyncWarningTimer:1,_updateConnectionStatus(){},_checkToolSyncWarning(){},_consumeMediaHandoff(){}});
sandbox.fetch=async()=>{entered.resolve(); return uploads.promise;};
const selected=kind==='image' ? file('photo.jpg','image/jpeg')
  : kind==='audio' ? file('memo.wav','audio/wav') : file('report.pdf','application/pdf');
let preparation;
if (kind==='image') preparation=ui.attachFile(selected);
else { await ui.attachFile(selected); preparation=ui.sendMessage(); }
await entered.promise;
const context=ui._attachmentSend || ui._imageUpload;
assert.ok(context);
client._emit('connectionChange',{connected:false});
client._emit('sessionReady',{mode:'cloud'});
assert.equal(outgoing[0][0],'conversation:load');
assert.equal(outgoing[0][1].reconnect_only,true);
assert.equal(context.controller.signal.aborted,false);
await app._displayLoadedConversation({id:'thread',messages:[]}, {reconcile:true});
assert.equal(context.controller.signal.aborted,false);
assert.equal(ui._attachmentSend || ui._imageUpload,context);
assert.equal(ui.stopBtn.disabled,false);
uploads.resolve(kind==='image'
  ? {ok:true,json:async()=>({ok:true,images:[{url:'/photo.jpg',filename:'photo.jpg'}]})}
  : response(kind,selected.name));
await preparation;
assert.equal(context.controller.signal.aborted,false);
assert.equal(outgoing.filter(([event])=>event==='chat:send').length,kind==='image'?0:1);
if (kind==='image') assert.equal(ui.pendingImageBatch.length,1);
""")


def test_socket_reconnect_keeps_live_cards_and_reactions_and_only_appends_missed_answers():
    run_browser(SETUP + r"""
app.audioEnabled=false;
client._emit('response',{message_id:'answer',conversation_id:'thread',text:'Live answer',tools_used:[]});
ui.rememberRenderedMessage('user','request');
const toolCard={expanded:true}, feedbackCard={rating:5}, reactionButtons={enabled:true};
ui.pendingTools={search:toolCard};
ui.clearChat=()=>{throw Error('Reconnect must preserve the transcript and its controls')};
ui.showThinking=()=>{throw Error('Reconnect must preserve live tool cards')};
ui.currentMessageId='working'; ui.isProcessing=true;
ui.messagesContainer.append(toolCard,feedbackCard,reactionButtons);
const saved={id:'thread',messages:[
  {role:'user',content:'Original request',data:{_request_id:'request'}},
  {role:'assistant',content:'Live answer',data:{_web_message_id:'answer'}}
],run:{message_id:'working',status:'running',conversation_id:'thread'}};
await app._displayLoadedConversation(saved,{reconcile:true});
assert.deepEqual(rendered,['Live answer']);
assert.equal(ui.pendingTools.search,toolCard);
assert.equal(ui.messagesContainer.children[1],feedbackCard);
assert.equal(ui.messagesContainer.children[2],reactionButtons);
assert.equal(ui.stopBtn.disabled,false);
saved.messages.push({role:'assistant',content:'Missed answer',data:{_web_message_id:'working'}});
saved.run.status='completed';
await app._displayLoadedConversation(saved,{reconcile:true});
await app._displayLoadedConversation(saved,{reconcile:true});
assert.deepEqual(rendered,['Live answer','Missed answer']);
assert.deepEqual(played,[]);
""")


def test_reconnect_does_not_resurrect_auto_accepted_completion_guard():
    run_browser(SETUP + r"""
ui.rememberRenderedMessage('assistant','answer');
let created=0, removed=0;
ui._ensureCompletionGuardCard=()=>{created++; return null;};
ui.messagesContainer.querySelector=()=>null;
const snapshot={id:'thread',messages:[
  {role:'assistant',content:'Saved answer',data:{
    _web_message_id:'answer',_completion_guard:{status:'auto_accepted'}
  }}
]};
await app._displayLoadedConversation(snapshot,{reconcile:true});
assert.equal(created,0);
assert.deepEqual(rendered,[]);

// A stale card left by an earlier client should also disappear on reconnect.
const stale={remove:()=>removed++};
ui.messagesContainer.querySelector=selector=>selector.includes('completion-guard-card')?stale:null;
await app._displayLoadedConversation(snapshot,{reconcile:true});
assert.equal(created,0);
assert.equal(removed,1);
""")


def test_reconnect_recovers_missed_feedback_and_latest_reaction_eligibility():
    run_browser(SETUP + r"""
const feedback=[], reactions=[];
ui._updateFeedbackCard=data=>feedback.push(data.rating);
ui.addAssistantMessage=(text,tools,data,options)=>reactions.push(options.allowReaction);
const snapshot={id:'thread',messages:[{role:'assistant',content:'Answer',data:{_web_message_id:'answer'}}],
  reaction_message_id:'answer',
  feedback:{event:'feedback:complete',data:{message_id:'answer',conversation_id:'thread',rating:5,feedback_revision:'owner:2'}}};
await app._displayLoadedConversation(snapshot,{reconcile:true});
await app._displayLoadedConversation(snapshot,{reconcile:true});
assert.deepEqual(feedback,[5]);
assert.deepEqual(reactions,[true]);
""")


def test_rejected_mode_change_keeps_the_current_mode_and_preparing_draft():
    run_browser(SETUP + r"""
const outgoing=[];
client.socket={emit:(event,data)=>outgoing.push([event,data])};
app.modeSelect={value:'cloud'};
const context=ui._attachmentContext();
ui._attachmentSend=context;
client.setMode('local');
assert.equal(client.mode,'cloud');
client._emit('modeRejected',{error:'A task is running in the other mode'});
assert.equal(app.modeSelect.value,'cloud');
assert.equal(context.controller.signal.aborted,false);
assert.equal(ui._attachmentSend,context);
assert.equal(outgoing[0][0],'mode:set');
""")


def test_lost_feedback_context_stops_analyzing_without_retrying():
    run_browser(SETUP + r"""
const updates=[];
ui._updateFeedbackCard=data=>updates.push(data);
ui.pendingFeedback={message_id:'answer',status:'analyzing'};
ui.rememberRenderedMessage('assistant','answer');
await app._displayLoadedConversation({id:'thread',messages:[
  {role:'assistant',content:'Answer',data:{_web_message_id:'answer'}}
]},{reconcile:true});
assert.equal(updates.length,1);
assert.equal(updates[0].success,false);
assert.match(updates[0].error,/not retried/);
assert.equal(ui.pendingFeedback,null);
assert.deepEqual(sent,[]);
""")


def test_reopening_history_recreates_cached_feedback_even_when_revision_was_seen():
    run_browser(SETUP + r"""
const updates=[];
ui._updateFeedbackCard=data=>updates.push(data.rating);
app._feedbackRevision='old';
await app._displayLoadedConversation({id:'thread',messages:[
  {role:'assistant',content:'Answer',data:{_web_message_id:'answer'}}
],feedback:{event:'feedback:complete',data:{message_id:'answer',feedback_revision:'old',rating:4}}});
assert.deepEqual(updates,[4]);
""")


def test_remote_clear_removes_obsolete_transcript_but_keeps_upload_preparation():
    run_browser(SETUP + r"""
ui.rememberRenderedMessage('assistant','old');
const context=ui._attachmentContext();
ui._attachmentSend=context; ui.isProcessing=true;
let cleared=0;
const clear=ui.clearChat.bind(ui);
ui.clearChat=options=>{cleared++; return clear(options)};
await app._displayLoadedConversation({id:'thread',messages:[]},{reconcile:true});
assert.equal(cleared,1);
assert.equal(ui._renderedMessageIds.size,0);
assert.equal(context.controller.signal.aborted,false);
assert.equal(ui.isProcessing,true);
""")


def test_remote_clear_followed_by_new_turn_removes_obsolete_messages():
    run_browser(SETUP + r"""
ui.rememberRenderedMessage('user','old-user');
ui.rememberRenderedMessage('assistant','old-answer');
const context=ui._attachmentContext();
ui._attachmentSend=context;
let cleared=0;
const clear=ui.clearChat.bind(ui);
ui.clearChat=options=>{cleared++; return clear(options)};
await app._displayLoadedConversation({id:'thread',messages:[
  {role:'user',content:'New thread contents',data:{_request_id:'new-user'}},
  {role:'assistant',content:'New answer',data:{_web_message_id:'new-answer'}}
]},{reconcile:true});
assert.equal(cleared,1);
assert.equal(ui._renderedMessageIds.has('assistant:old-answer'),false);
assert.equal(ui._renderedMessageIds.has('assistant:new-answer'),true);
assert.equal(context.controller.signal.aborted,false);
""")


def test_restored_failure_deduplicates_late_socket_error():
    run_browser(SETUP + r"""
const run={conversation_id:'thread',message_id:'failed',status:'failed',error:'Known failure'};
await app._displayLoadedConversation({id:'thread',run,messages:[
  {role:'user',content:'Work',data:{_request_id:'failed',_run:run}}
]});
client._emit('error',{message_id:'failed',conversation_id:'thread',error:'Known failure'});
assert.deepEqual(rendered,['ERROR: Known failure']);
""")


def test_pre_admission_error_clears_receipt_and_removes_optimistic_bubble():
    run_browser(SETUP + r"""
client.conversationId=null;
client.pendingRequestId='rejected';
storage.set('jarvis.pendingRequest','rejected');
ui.inputField.value='';
let removed=0;
ui._pendingSend={requestId:'rejected',text:'Original draft',documents:[],images:[],
  element:{remove:()=>removed++},imageAction:'analyze',imageSettings:{},toolHints:[]};
ui.rememberRenderedMessage('user','rejected');
client._emit('error',{admitted:false,conversation_id:null,message_id:'rejected',error:'Invalid attachment'});
assert.equal(client.pendingRequestId,null);
assert.equal(new JarvisSocket().pendingRequestId,null);
assert.equal(removed,1);
assert.equal(ui._renderedMessageIds.has('user:rejected'),false);
assert.equal(ui.inputField.value,'Original draft');
assert.deepEqual(rendered,[]);
""")


def test_repair_response_keeps_stop_until_ticketing_settles():
    run_browser(SETUP + r"""
ui.restoreRunState({conversation_id:'thread',message_id:'repair',status:'running',kind:'repair'}, {fromSnapshot:true});
client._emit('response',{conversation_id:'thread',message_id:'repair',text:'Repair answer'});
assert.deepEqual(rendered,['Repair answer']);
assert.equal(ui.isProcessing,true);
assert.equal(ui.currentMessageId,'repair');
assert.equal(ui.stopBtn.disabled,false);
client._emit('runState',{conversation_id:'thread',message_id:'repair',status:'failed',kind:'repair'});
assert.equal(ui.isProcessing,false);
""")


def test_show_thinking_reuses_live_tool_card_container():
    run_browser(SETUP + r"""
const thinking={};
ui.messagesContainer.querySelector=selector=>selector==='.thinking-message'?thinking:null;
ui.hideThinking=()=>{throw new Error('Existing tools must stay in place')};
ChatUI.prototype.showThinking.call(ui);
assert.equal(ui.stopBtn.style.display,'flex');
""")


def test_reconnect_retains_available_controls_and_expires_evicted_review_context():
    run_browser(SETUP + r"""
const removed=[], guardUpdates=[];
const actions={querySelectorAll:()=>[{remove:()=>removed.push('reaction')}]};
ui.messagesContainer.querySelector=selector=>selector.includes('message-response-actions')?actions:{};
ui._updateCompletionGuardCard=data=>guardUpdates.push(data.status);
const conversation={id:'thread',reaction_message_id:'answer',completion_guards:{answer:{prompt_user:true}},
  messages:[{role:'assistant',data:{_web_message_id:'answer',_completion_guard:{status:'pending'}}}]};
ui.reconcileLiveActions(conversation);
assert.deepEqual(removed,[]);
assert.deepEqual(guardUpdates,[]);
delete conversation.reaction_message_id;
delete conversation.completion_guards;
ui.reconcileLiveActions(conversation);
assert.deepEqual(removed,['reaction']);
assert.deepEqual(guardUpdates,['expired']);
""")


def test_new_chat_releases_the_old_conversations_disabled_mode_selector():
    run_browser(SETUP + r"""
app.modeSelect={disabled:true};
ui.refreshContextWindow=()=>{};
app._startNewChat();
assert.equal(app.modeSelect.disabled,false);
assert.equal(client.conversationId,null);
""")
