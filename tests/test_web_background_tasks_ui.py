"""Execute the shipped composer, event reducer and late-message rendering in Node."""

from test_web_attachment_bundle_ui import run_browser
from test_web_task_recovery_ui import SETUP

BACKGROUND = (
    SETUP
    + r"""
sandbox.document.getElementById=()=>null;
Element.prototype.prepend=function(item){this.children.unshift(item);};
const BackgroundTasks=loadClass(ROOT+'/jarvis-web/client/js/background-tasks.js','BackgroundTasks','window.BackgroundTasks');
const manager=new BackgroundTasks(app);
vm.runInContext(fs.readFileSync(ROOT+'/jarvis-web/client/js/continuation-renderer.js','utf8'),sandbox);
app.backgroundTasks=manager;
vm.runInContext(fs.readFileSync(ROOT+'/jarvis-web/client/js/media-result-renderer.js','utf8'),sandbox);
manager.generations.set('thread',0);
app._displayedConversationId='thread';
const receipt={schema_version:1,conversation_id:'thread',generation:0,job_id:'job-1',source_message_id:'first',
  revision:1,tool:'fixture',state:'queued'};
const late={schema_version:1,conversation_id:'thread',generation:0,job_id:'job-1',continuation_id:'late-1',
  message:{content:'Fixture finished',data:{_kind:'continuation'}}};
"""
)


def test_late_events_leave_foreground_tool_draft_attachments_and_audio_untouched():
    run_browser(
        BACKGROUND
        + r"""
ui.pendingTools={get_time:{status:'running'}};
ui.currentMessageId='second';ui.isProcessing=true;ui.sendBtn.disabled=true;
ui.inputField.value='Unsent follow-up';ui.attachedDocuments=[{uploadId:'keep'}];
const before=JSON.stringify({tools:ui.pendingTools,id:ui.currentMessageId,processing:ui.isProcessing,
  disabled:ui.sendBtn.disabled,draft:ui.inputField.value,files:ui.attachedDocuments});
client._emit('taskUpdated',{...receipt,state:'succeeded',revision:2});
client._emit('continuation',late);
client._emit('continuation',late);
assert.deepEqual(rendered,['Fixture finished']);
assert.deepEqual(played,[]);
assert.equal(JSON.stringify({tools:ui.pendingTools,id:ui.currentMessageId,processing:ui.isProcessing,
  disabled:ui.sendBtn.disabled,draft:ui.inputField.value,files:ui.attachedDocuments}),before);
assert.equal(manager.jobs.get('job-1').state,'succeeded');
"""
    )


def test_stale_generations_other_conversations_and_older_revisions_are_ignored():
    run_browser(
        BACKGROUND
        + r"""
client._emit('taskUpdated',{...receipt,revision:4,state:'succeeded'});
client._emit('taskUpdated',{...receipt,revision:2,state:'running'});
assert.equal(manager.jobs.get('job-1').state,'succeeded');
manager.generations.set('thread',1);
client._emit('tasksSnapshot',{conversation_id:'thread',generation:0,jobs:[receipt]});
assert.equal(manager.generations.get('thread'),1);
await app._displayLoadedConversation({id:'thread',generation:0,messages:[{role:'assistant',content:'Stale snapshot'}]});
client._emit('continuation',late);
client._emit('taskUpdated',{...receipt,revision:5});
assert.deepEqual(rendered,[]);
client._emit('continuation',{...late,conversation_id:'other'});
assert.deepEqual(rendered,[]);
manager.generations.set('other',0);
client._emit('continuation',{...late,conversation_id:'other'});
assert.equal(manager.unread.has('other'),true);
assert.equal(ui.currentMessageId,null);
"""
    )


def test_result_card_updates_in_place_with_inert_text_and_delayed_reply_status():
    run_browser(
        BACKGROUND
        + r"""
const message=new Element();
message.querySelectorAll=selector=>selector==='[data-background-job]'?message.children:[];
const unsafe='<img src=x onerror=alert(1)>';
manager.renderCards(message,{'job-1':{...receipt,tool:unsafe}});
const card=message.children[0];card.open=true;
manager.renderCards(message,{'job-1':{...receipt,revision:2,state:'succeeded',result:{summary:unsafe},
  delivery_error:'Summary unavailable',delivery_state:'pending'}});
assert.equal(message.children.length,1);
assert.equal(message.children[0],card);
assert.equal(card.open,true);
assert.match(card.children[0].textContent,/reply delayed/);
assert.match(card.children[1].textContent,/<img src=x onerror=alert\(1\)>/);
assert.equal(card.children[1].innerHTML,'');
"""
    )


def test_browser_task_card_requests_cancellation_for_its_revision():
    run_browser(BACKGROUND + r"""
const message=new Element();
message.querySelectorAll=selector=>selector==='[data-background-job]'?message.children:[];
const requests=[];
sandbox.Utils.auth={fetch:async(url,options)=>{
  requests.push({url,options});return {ok:true,json:async()=>({job:{state:'cancel_requested'}})};
}};
manager.renderCards(message,{'job-1':{...receipt,tool:'browser_use',state:'running',can_cancel:true,revision:7}});
const cancel=message.children[0].children[2];
assert.equal(cancel.textContent,'Request cancellation');
await cancel.click({preventDefault(){},stopPropagation(){}});
assert.equal(requests[0].url,'/api/background-jobs/job-1/actions');
assert.deepEqual(JSON.parse(requests[0].options.body),{action:'cancel',revision:7});
manager.renderCards(message,{'job-1':{...receipt,tool:'browser_use',state:'cancel_requested',can_cancel:false,revision:8}});
assert.equal(message.children[0].children.length,2);
manager.renderCards(message,{'job-1':{...receipt,tool:'browser_use',mode:'cloud',state:'cancelled',can_cancel:false,revision:9,
  result:{ok:false,speech:'Partial research',data:{browser_research:{stash_ref:'stash://space/report'}}}}});
assert.equal(message.children[0].children[2].textContent,'Open saved research');
assert.equal(message.children[0].children[2].href,'/stash/view/space/report?mode=cloud');
""")


def test_actual_assistant_renderer_does_not_reconcile_or_clear_a_foreground_tool():
    run_browser(
        BACKGROUND
        + r"""
ui.addAssistantMessage=ChatUI.prototype.addAssistantMessage;
ui.pendingTools={generate_image_0:{status:'running'},generate_video_0:{status:'running'},convert_file_0:{status:'running'}};
ui.currentMessageId='second';ui.isProcessing=true;
ui._reconcilePendingToolsWithFinalList=()=>{throw Error('Late result must not reconcile foreground tools');};
ui._clearPendingToolsForMessage=()=>{throw Error('Late result must not clear foreground tools');};
ui._attachCompletionGuardCard=()=>{throw Error('Continuation cannot be audited');};
ui._attachMessageResponseActions=()=>{};
ui._extractCanvasPreview=()=>null;ui._collectYouTubeEmbeds=()=>[];
sandbox.Utils.stripLlmCitationArtifacts=value=>value;
sandbox.Utils.parseMarkdown=value=>value;
sandbox.Utils.hydrateRichContent=()=>{};
sandbox.window.assistantMessageRenderer={renderToolCards(entries){assert.equal(entries.length,0);return '';},
  renderShoppingFallback:()=>'',renderConvertedFile:()=>{throw Error('Unrelated foreground conversion');}};
const before=JSON.stringify(ui.pendingTools);
client._emit('continuation',late);
assert.equal(ui.messagesContainer.children.length,1);
assert.equal(ui.messagesContainer.children[0].dataset.messageId,'late-1');
assert.equal(JSON.stringify(ui.pendingTools),before);
assert.equal(ui.currentMessageId,'second');assert.equal(ui.isProcessing,true);
assert.deepEqual(played,[]);
"""
    )


def test_chat_send_uses_server_preferences_without_one_shot_selection():
    run_browser(
        BACKGROUND
        + r"""
const sent=[];
client.socket={emit:(event,data)=>sent.push([event,data])};
await ui.sendMessage();
const message=sent.find(([event])=>event==='chat:send')[1];
assert.equal(Object.hasOwn(message,'background_tools'),false);
assert.equal(fs.readFileSync(ROOT+'/jarvis-web/client/index.html','utf8').includes('id="backgroundControl"'),false);
"""
    )


def test_remote_settings_explain_outcomes_and_keep_convert_readiness_independent():
    run_browser(BACKGROUND + r"""
manager.control=new Element('section');
manager.enabledInput=new Element('input'); manager.choices=new Element('div'); manager.note=new Element('p');
const convertNote=new Element('p');
sandbox.document.getElementById=id=>id==='convertExecutionNote'?convertNote:null;
const media=['generate_image','generate_video','generate_music','create_social_clip'];
const status={settings:{background_enabled:true,background_tools:['convert_file']},
  tools:['convert_file',...media],configured_tools:['convert_file',...media],
  coordinator_ready:true,worker_ready:true,tool_details:{
    convert_file:{remote_work:false,worker_ready:true},
    ...Object.fromEntries(media.map(name=>[name,{remote_work:true,worker_ready:true}]))}};
sandbox.Utils.auth={fetch:async()=>({ok:true,json:async()=>status})};
await manager.refresh();
assert.equal(manager.choices.children.length,5);
const remote=manager.choices.children[1];
assert.equal(remote.children[0].checked,false);
assert.match(remote.children[1].children[0].textContent,/does not cancel provider work/);
assert.match(convertNote.textContent,/Runs in the background/);
status.tool_details.generate_image.worker_ready=false;
await manager.refresh();
assert.match(manager.choices.children[1].children[1].children[0].textContent,/started or restarted/);
assert.match(convertNote.textContent,/Runs in the background/);
// An unavailable tool cannot be newly selected. Saved cross-mode intent stays
// visible and can be cleared, but does not make the tool executable here.
status.tools=status.tools.filter(name=>name!=='create_social_clip');
await manager.refresh();
let clip=manager.choices.children[4].children[0];
assert.equal(clip.disabled,true);
assert.equal(clip.checked,false);
status.settings.background_tools.push('create_social_clip');
await manager.refresh();
clip=manager.choices.children[4].children[0];
assert.equal(clip.checked,true);
assert.equal(clip.disabled,false);
assert.match(manager.choices.children[4].children[1].children[0].textContent,/Saved preference retained/);
status.tools.push('create_social_clip');
await manager.refresh();
assert.equal(manager.choices.children[4].children[0].disabled,false);
""")


def test_private_callback_settings_report_policy_and_mode_readiness():
    run_browser(BACKGROUND + r"""
manager.control=new Element('section');
manager.enabledInput=new Element('input');manager.choices=new Element('div');manager.note=new Element('p');
const callback={policy_ready:false,source_ready:true,service_ready:true};
const status={settings:{background_enabled:true,background_tools:[]},tools:['private_task'],
  configured_tools:['private_task'],coordinator_ready:true,worker_ready:true,
  tool_details:{private_task:{worker_ready:true,private_callback:callback}}};
sandbox.Utils.auth={fetch:async()=>({ok:true,json:async()=>status})};
await manager.refresh();
let row=manager.choices.children[0];
assert.equal(row.children[0].disabled,true);
assert.match(row.children[1].children[0].textContent,/policy changed/);
callback.policy_ready=true;
await manager.refresh();
row=manager.choices.children[0];
assert.equal(row.children[0].disabled,false);
assert.match(row.children[1].children[0].textContent,/Ready for Web chat/);
status.tools=[];
status.settings.background_tools=['private_task'];
await manager.refresh();
row=manager.choices.children[0];
assert.equal(row.children[0].checked,true);
assert.match(row.children[1].children[0].textContent,/Unavailable in this mode/);
""")


def test_browser_use_has_one_setup_action_and_cannot_be_selected_before_readiness():
    run_browser(BACKGROUND + r"""
manager.control=new Element('section');
manager.enabledInput=new Element('input');manager.choices=new Element('div');manager.note=new Element('p');
const status={settings:{background_enabled:false,background_tools:[]},tools:['browser_use'],
  configured_tools:['browser_use'],coordinator_ready:true,worker_ready:false,
  tool_details:{browser_use:{remote_work:false,worker_ready:false,browser_use:{configured:false,
    receiver_enabled:false,source_enabled:false,source_validated:false,credential_ready:false,
    service_ready:false,worker_ready:false,selected:false,managed_by_tmux:false,operational:false,ready:false}}}};
const calls=[];
sandbox.Utils.auth={fetch:async(url,options={})=>{
  calls.push({url,options});
  if(options.method==='POST') status.tool_details.browser_use.browser_use.setup={state:'running',message:'Downloading pinned image…'};
  return {ok:true,status:options.method==='POST'?202:200,
    json:async()=>options.method==='POST'?{browser_use:status.tool_details.browser_use.browser_use}:status};
}};
await manager.refresh();
const row=manager.choices.children[0];
assert.equal(row.children[0].disabled,true);
assert.equal(row.children[2].children[0].textContent,'Set up and enable');
await row.children[2].children[0].click({preventDefault(){},stopPropagation(){}});
const action=calls.find(item=>item.options.method==='POST');
assert.equal(action.url,'/api/background-tasks/tools/browser_use/actions');
assert.deepEqual(JSON.parse(action.options.body),{action:'setup'});
assert(notices.some(item=>String(item[0]).includes('setup started')));
assert.equal(manager.choices.children[0].children[2].children[0].disabled,true);
status.tool_details.browser_use.browser_use.setup={state:'ready',message:'Browser Use is configured and enabled.'};
await manager.refresh();
assert(notices.some(item=>String(item[0]).includes('configured and enabled')));
""")


def test_browser_use_docker_row_explains_native_only_without_setup_action():
    run_browser(BACKGROUND + r"""
manager.control=new Element('section');
manager.enabledInput=new Element('input');manager.choices=new Element('div');manager.note=new Element('p');
const status={settings:{background_enabled:false,background_tools:[]},tools:['browser_use'],
  configured_tools:['browser_use'],coordinator_ready:true,worker_ready:true,
  tool_details:{browser_use:{worker_ready:false,browser_use:{deployment_supported:false,
    configured:false,operational:false,ready:false,setup:{state:'unsupported',message:'Native only'}}}}};
const calls=[];
sandbox.Utils.auth={fetch:async(url,options={})=>{
  calls.push({url,options});return {ok:true,status:200,json:async()=>status};
}};
await manager.refresh();
const row=manager.choices.children[0];
assert.equal(row.children[0].disabled,true);
assert.match(row.children[1].children[0].textContent,/Native install only.*unavailable.*Docker/);
assert.equal(row.children.length,2);
assert.equal(calls.length,1);
status.settings.background_enabled=true;
status.settings.background_tools=['browser_use'];
await manager.refresh();
assert.equal(manager.choices.children[0].children[0].checked,true);
assert.equal(manager.choices.children[0].children[0].disabled,false);
assert.match(manager.note.textContent,/Selected background tools are unavailable/);
""")


def test_background_composer_does_not_send_a_duplicate_policy_override():
    run_browser(BACKGROUND + r"""
assert.equal(fs.readFileSync(ROOT+'/jarvis-web/client/index.html','utf8').includes('backgroundRepeats'),false);
client.socket={emit:(event,data)=>sent.push([event,data])};
manager.enabled=true;
const choice={value:'fixture',checked:true};
manager.choices={querySelectorAll:selector=>selector.includes(':checked')?(choice.checked?[choice]:[]):[choice]};
await ui.sendMessage();
const message=sent.find(([event])=>event==='chat:send')[1];
assert.equal(Object.hasOwn(message,'allow_repeated_background'),false);
// Even stale prompt metadata does not reintroduce the removed flag.
client.sendMessage('next',null,{background_tools:['fixture'],allow_repeated_background:true});
assert.equal(sent.filter(([event])=>event==='chat:send').length,2);
assert.equal(Object.hasOwn(sent.filter(([event])=>event==='chat:send').at(-1)[1],'allow_repeated_background'),false);
assert.equal(Object.hasOwn(sent.filter(([event])=>event==='chat:send').at(-1)[1],'background_tools'),false);
""")


def test_convert_popup_uploads_and_sends_without_a_composer_background_switch():
    run_browser(BACKGROUND + r"""
client.socket={emit:(event,data)=>sent.push([event,data])};
ui.pendingConvertFile={file:file('example.png','image/png')};
ui.convertTargetFormat={value:'jpg'};
ui._collectConvertOptions=()=>({quality:90});
ui._hideConvertModal=()=>{ui.pendingConvertFile=null;};
sandbox.fetch=async(url,options)=>{requests.push({url,options});return {ok:true,json:async()=>({stash_ref:'stash://example.png'})};};
await ui._executeConversion();
await new Promise(resolve=>setTimeout(resolve,0));
assert.equal(requests.length,1);assert.equal(requests[0].url,'/api/stash/upload');
const messages=sent.filter(([event])=>event==='chat:send');
assert.equal(messages.length,1);
assert.match(messages[0][1].message,/stash:\/\/example.png to JPG format with options: quality=90/);
assert.match(messages[0][1].message,/Use the convert_file tool/);
assert.equal(Object.hasOwn(messages[0][1],'background_tools'),false);
assert.equal(JSON.stringify(messages[0][1].tool_action),JSON.stringify({tool:'convert_file',
  arguments:{source:'stash://example.png',target_format:'jpg',options:{quality:90}}}));
// The popup's initial Web turn remains busy until its saved receipt arrives.
const firstId=messages[0][1].request_id;
assert.equal(ui.isProcessing,true);
assert.equal(ui.sendBtn.disabled,true);
client._emit('runState',{conversation_id:'thread',message_id:firstId,kind:'chat',
  status:'completed',started_at:1,finished_at:2});
client._emit('response',{conversation_id:'thread',message_id:firstId,text:'Conversion queued.',
  tools_used:[],data:{pending_jobs:[{job_id:'job-1',tool:'convert_file',status:'accepted'}]}});
client._emit('taskUpdated',{...receipt,source_message_id:firstId,tool:'convert_file',state:'running',revision:2});
assert.equal(ui.isProcessing,false);
ui.inputField.value='Hello, how are you?';
ui.updateSendButton();
assert.equal(ui.sendBtn.disabled,false);
await ui.sendMessage();
assert.equal(sent.filter(([event])=>event==='chat:send').length,2);
assert.equal(sent.filter(([event])=>event==='chat:send')[1][1].message,'Hello, how are you?');
// A late conversion answer cannot settle the newly submitted foreground turn.
const secondId=ui.currentMessageId;
client._emit('continuation',late);
assert.equal(ui.currentMessageId,secondId);
assert.equal(ui.isProcessing,true);
""")


def test_task_manager_controls_pagination_safe_details_and_reconciliation():
    run_browser(BACKGROUND + r"""
sandbox.URLSearchParams=URLSearchParams;
sandbox.document.body=new Element();
sandbox.document.createElement=tag=>{const el=new Element(tag);el.value='';return el;};
Element.prototype.showModal=function(){this.open=true;};
const launch=new Element('button');
sandbox.document.getElementById=id=>id==='backgroundTasksButton'?launch:null;
vm.runInContext(fs.readFileSync(ROOT+'/jarvis-web/client/js/task-manager.js','utf8'),sandbox);
const view=new sandbox.window.TaskManager(manager);
const unsafe='<img src=x onerror=alert(1)>';
const job={...receipt,tool:unsafe,state:'needs_attention',mode:'cloud',created_at:1,revision:3,unread:true,
  can_reconcile:true,can_cancel:false,can_retry_delivery:false,can_suppress_delivery:false};
const counts={outstanding:1,running:0,reserved:1,unread:1};
const settings={background_enabled:false,max_running:2,max_per_adapter:2,max_outstanding:5,max_queued:100};
const calls=[];
sandbox.Utils.auth={fetch:async(url,options={})=>{
  calls.push([url,options.body?JSON.parse(options.body):null,options.method]);
  const body=url.includes('/actions')?{job:{...job,id:'job-1',revision:4,admission:{arguments:{source:unsafe}},
    attempts:[],operator_events:[],result:{speech:unsafe}}}:
    url.startsWith('/api/background-jobs?')?{jobs:[job],total:26,next_offset:25,counts}:
    {settings,counts,worker_ready:false,tools:[]};
  return {ok:true,json:async()=>body};
}};
await view.open();
assert.equal(view.next.disabled,false);assert.equal(view.previous.disabled,true);
assert.equal(view.statValues.reserved.textContent,'1');
assert.equal(view.summary.textContent,'Worker offline');
assert.match(launch.title,/1 unread/);
assert.equal(view.rows.children[0].children[0].innerHTML,'');
assert.match(view.rows.children[0].children[0].children[0].textContent,/<img/);
await view.inspect('job-1');
assert.equal(calls.some(([url,body])=>body?.action==='read'),true);
const all=node=>[node,...node.children.flatMap(child=>all(child))];
const nodes=all(view.details);
nodes.find(el=>el.tag==='textarea').value='Verified the original process group has exited.';
nodes.find(el=>el.tag==='input').checked=true;
nodes.find(el=>el.tag==='select').value='failed';
nodes.find(el=>el.textContent==='Record reconciliation').click();
await new Promise(resolve=>setTimeout(resolve,10));
const reconcile=calls.find(([url,body])=>body?.action==='reconcile')[1];
assert.equal(reconcile.revision,4);assert.equal(reconcile.stopped,true);
assert.equal(reconcile.disposition,'failed');
assert.equal(calls.some(([url])=>url.includes('/api/alerts')),false);
""")


def test_task_details_artifact_links_keep_job_mode_after_chat_mode_switch():
    run_browser(BACKGROUND + r"""
sandbox.document.body=new Element();
sandbox.document.createElement=tag=>{const el=new Element(tag);el.value='';return el;};
vm.runInContext(fs.readFileSync(ROOT+'/jarvis-web/client/js/task-manager.js','utf8'),sandbox);
const view=new sandbox.window.TaskManager(manager);
view.refresh=async()=>{};
const all=node=>[node,...node.children.flatMap(all)];
for (const [original,current] of [['cloud','local'],['local','cloud']]) {
  client.mode=current;
  const job={id:'job-1',state:'succeeded',mode:original,admission:{arguments:{}},
    result:{ok:true,data:{saved:{
      stash_ref:'stash://space_result/file_result',filename:'converted.jpg'}}},
    attempts:[],operator_events:[]};
  const before=JSON.stringify(job);
  sandbox.Utils.auth={fetch:async()=>({ok:true,json:async()=>({job})})};
  await view.inspect(job.id);
  const links=all(view.details).filter(el=>el.tag==='a');
  assert.equal(links.length,1);
  assert.equal(links[0].href,'/stash/view/space_result/file_result?mode='+original);
  assert.equal(JSON.stringify(job),before);
  assert.equal(client.mode,current);
  // Renderer metadata in a tool result cannot override the stored job mode.
  job.result._background_mode=current;
  await view.inspect(job.id);
  assert.equal(all(view.details).find(el=>el.tag==='a').href,links[0].href);
  assert.equal(job.result._background_mode,current);
  // A task without retained output must still open without artifact links.
  job.result=null;
  await view.inspect(job.id);
  assert.equal(all(view.details).filter(el=>el.tag==='a').length,0);
}
""")


def test_mode_switch_with_pending_job_keeps_current_foreground_and_original_card():
    run_browser(BACKGROUND + r"""
for (const [original,current] of [['cloud','local'],['local','cloud']]) {
  client.socket={emit:(event,data)=>sent.push([event,data])};
  client.mode=original;manager.jobs.clear();manager.revisions.clear();
  client._emit('taskUpdated',{...receipt,mode:original});
  // Execute the shipped composer mode-control binding.
  app.modeSelect=new Element('select');
  const source=fs.readFileSync(ROOT+'/jarvis-web/client/js/app.js','utf8');
  const binding=source.slice(source.indexOf("    this.modeSelect.addEventListener('change'"), source.indexOf('    // Audio toggle'));
  vm.runInContext('(function(){'+binding+'})',sandbox).call(app);
  app.modeSelect.change({target:{value:current}});
  assert.equal(sent.at(-1)[0],'mode:set');assert.equal(sent.at(-1)[1].mode,current);
  client.mode=current;
  ui.pendingTools={get_time:{status:'running'}};ui.currentMessageId='second';ui.isProcessing=true;
  client._emit('taskUpdated',{...receipt,mode:original,state:'succeeded',revision:2});
  assert.equal(manager.jobs.get('job-1').mode,original);
  assert.equal(client.mode,current);assert.equal(ui.currentMessageId,'second');
  assert.equal(ui.pendingTools.get_time.status,'running');
}
""")


def test_retention_preview_stays_beside_button_through_refresh_and_reports_errors():
    run_browser(BACKGROUND + r"""
sandbox.URLSearchParams=URLSearchParams;
sandbox.document.body=new Element();
sandbox.document.createElement=tag=>{const el=new Element(tag);el.value='';return el;};
Element.prototype.showModal=function(){this.open=true;};
Element.prototype.scrollIntoView=function(){this.scrolled=true;};
vm.runInContext(fs.readFileSync(ROOT+'/jarvis-web/client/js/task-manager.js','utf8'),sandbox);
const view=new sandbox.window.TaskManager(manager);
let preview=deferred();
const calls=[];
sandbox.Utils.auth={fetch:async(url,options={})=>{
  calls.push([url,options]);
  if(url==='/api/background-tasks/retention')return preview.promise;
  return {ok:true,json:async()=>url.startsWith('/api/background-jobs?')
    ? {jobs:[],total:0,next_offset:null,counts:{}}
    : {settings:{background_enabled:true,result_retention_days:30},counts:{},worker_ready:true,tools:[]}};
}};
await view.open();
const all=node=>[node,...node.children.flatMap(all)];
const advanced=all(view.dialog).find(el=>el.tag==='details'&&el.className==='task-advanced');
assert.ok(advanced.children.includes(view.retentionPreview));
assert.equal(view.retentionPreview.hidden,true);
view.retentionButton.click();
await new Promise(resolve=>setTimeout(resolve,0));
assert.equal(view.retentionButton.disabled,true);
assert.match(view.retentionPreview.textContent,/Checking/);
preview.resolve({ok:true,json:async()=>({eligible_in_next_batch:0,batch_limit:100})});
await new Promise(resolve=>setTimeout(resolve,0));
assert.equal(view.retentionButton.disabled,false);
assert.equal(view.retentionPreview.scrolled,true);
assert.match(view.retentionPreview.textContent,/No finished task results/);
assert.match(view.retentionPreview.textContent,/nothing was changed/);
await view.refresh();
assert.match(view.retentionPreview.textContent,/No finished task results/);
assert.equal(view.summary.textContent,'Ready for background work');
preview=deferred();
const pending=view.previewRetention();
preview.resolve({ok:true,json:async()=>({eligible_in_next_batch:3,batch_limit:100})});
await pending;
assert.match(view.retentionPreview.textContent,/3 finished task results.*up to 100/);
preview=deferred();
const failed=view.previewRetention();
preview.resolve({ok:false,json:async()=>({error:'Storage unavailable'})});
await failed;
assert.equal(view.retentionPreview.dataset.error,'true');
assert.match(view.retentionPreview.textContent,/Could not preview retention: Storage unavailable/);
assert.equal(view.retentionButton.disabled,false);
assert.ok(calls.every(([url,options])=>!options.method&&!options.body));
""")


def test_delivered_task_unread_label_clears_only_after_inspection():
    run_browser(BACKGROUND + r"""
sandbox.URLSearchParams=URLSearchParams;
sandbox.document.body=new Element();
sandbox.document.createElement=tag=>{const el=new Element(tag);el.value='';return el;};
Element.prototype.showModal=function(){this.open=true;};
vm.runInContext(fs.readFileSync(ROOT+'/jarvis-web/client/js/task-manager.js','utf8'),sandbox);
const view=new sandbox.window.TaskManager(manager);
const job={...receipt,tool:'generate_image',state:'succeeded',delivery_state:'delivered',unread:true,
  mode:'cloud',created_at:1,admission:{arguments:{}},result:{},attempts:[],operator_events:[]};
sandbox.Utils.auth={fetch:async(url,options={})=>{
  if(options.body) {
    assert.equal(JSON.parse(options.body).action,'read');job.unread=false;
    return {ok:true,json:async()=>({job})};
  }
  return {ok:true,json:async()=>url.startsWith('/api/background-jobs?')
    ? {jobs:[job],total:1,next_offset:null,counts:{}}
    : {settings:{background_enabled:true},counts:{},worker_ready:true,tools:[]}};
}};
const all=node=>[node,...node.children.flatMap(all)];
await view.open();
assert.equal(all(view.rows).filter(el=>el.className==='task-unread').length,1);
assert.equal(all(view.rows).find(el=>el.className==='task-unread').textContent,'Unread');
assert.equal(all(view.rows).find(el=>el.tag==='strong').textContent,'generate image');
await view.inspect('job-1');
assert.equal(all(view.rows).filter(el=>el.className==='task-unread').length,0);
assert.equal(job.delivery_state,'delivered');
""")
