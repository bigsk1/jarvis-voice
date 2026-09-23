"""Execute the actual browser attachment methods with disposable fake I/O."""

import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

HARNESS = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const notices = [], sent = [], requests = [], revoked = [];
class Element {
  constructor(tag = 'div') { this.tag = tag; this.children = []; this.style = {}; this.dataset = {}; this.innerHTML = ''; this.classList = {add(){},remove(){},toggle(){}}; }
  append(...items) { this.children.push(...items); }
  appendChild(item) { this.children.push(item); }
  replaceChildren(...items) { this.children = items; }
  querySelector() { return null; }
  querySelectorAll(selector) { return this.children.flatMap(item => [...(selector === item.tag ? [item] : []), ...item.querySelectorAll(selector)]); }
  addEventListener(event, callback) { this[event] = callback; }
  setAttribute(key, value) { this[key] = value; }
  remove() {}
  pause() { this.paused = true; }
  focus() {}
}
class FormDataFake {
  constructor() { this.entries = {}; }
  append(key, value) { this.entries[key] = value; }
}
let fileCounter = 0;
function file(name, type = '', size = 10) { return {name, type, size}; }
function response(kind, name, id = ++fileCounter) {
  return {ok: true, json: async () => ({ok: true, attachment: {kind, filename: name, stash_ref: `stash://space_test_${id}/f_${id}`, mime_type: kind === 'audio' ? 'audio/wav' : 'text/plain'}})};
}
function deferred() { let resolve, reject; const promise = new Promise((a,b) => {resolve=a;reject=b;}); return {promise,resolve,reject}; }
const socket = {connected: true, mode: 'cloud', conversationId: 'a', sendMessage(...args) {sent.push(args); return this.connected;}, socket: {emit() {}}};
const sandbox = {
  crypto: require('node:crypto').webcrypto,
  console, URL, AbortController, FormData: FormDataFake, setTimeout, clearTimeout, history: {replaceState(){}},
  document: {createElement: tag => new Element(tag), querySelectorAll: () => []},
  Utils: {toast: (...args) => notices.push(args), autoResize(){}, scrollToBottom(){}, escapeHtml: value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;'), storage: {get: (_key, fallback) => fallback}},
  window: {jarvisSocket: socket, URL: {createObjectURL: () => `blob:${++fileCounter}`, revokeObjectURL: url => revoked.push(url)}, commandSystem: {parseInput: message => ({message, toolHints: []}), getActiveDisplay: () => '', getPersistedDisplay: () => ''}},
  fetch: async (url, options) => { requests.push({url, ...options}); const fields = options.body.entries; return response(url.split('-').pop(), fields.file.name); }
};
vm.createContext(sandbox);
const utilsSource = fs.readFileSync(ROOT + '/jarvis-web/client/js/utils.js', 'utf8');
const stashStart = utilsSource.indexOf('  stashRefToApiUrl(');
const stashMethod = utilsSource.slice(stashStart, utilsSource.indexOf('\n  /**', stashStart)).trim().replace(/,$/, '');
sandbox.Utils.stashRefToApiUrl = vm.runInContext(`({${stashMethod}}).stashRefToApiUrl`, sandbox);
function loadClass(path, name, terminator) {
  const source = fs.readFileSync(path, 'utf8');
  return vm.runInContext(source.slice(source.indexOf(`class ${name}`), source.lastIndexOf(terminator)) + `\n${name}`, sandbox);
}
const ChatUI = loadClass(ROOT + '/jarvis-web/client/js/chat.js', 'ChatUI', '// Create global instance');
const JarvisApp = loadClass(ROOT + '/jarvis-web/client/js/app.js', 'JarvisApp', '// Initialize app');
const JarvisSocket = loadClass(ROOT + '/jarvis-web/client/js/socket.js', 'JarvisSocket', '// Create global instance');
function chat() {
  const value = Object.create(ChatUI.prototype);
  Object.assign(value, {attachedDocuments: [], attachedImages: [], imageAttachmentAction:'analyze', imageAttachmentSettings:{}, _attachmentEpoch:0, _attachmentSend:null, _imageUpload:null, pendingImageBatch:null, filePreviewContainer:new Element(), inputField:new Element(), messagesContainer:new Element(), sendBtn:new Element(), stopBtn:new Element(), selectedToolHints:[], isProcessing:false, chatOnlyEnabled:false, feedbackEnabled:false, pendingVisionRetryPayload:null, currentMessageId:null});
  value.inputField.value = 'Compare these sources';
  for (const key of ['_hideAutocomplete','_expirePendingCompletionGuardCards','_resetPendingToolState','_renderToolHintChips','_hideAmbientToolSuggestions','showThinking','hideThinking','showProgressStatus','clearStatus','_resetProcessingUi','_resetTokenCounter']) value[key] = () => {};
  value._combineToolHints = hints => hints;
  value._showImageActionModal = async uploads => {value.pendingImageBatch = uploads;};
  value._normalizeAudioAttachment = item => item;
  value._renderAudioPlayerHtml = item => `<audio data-source="${item.stash_ref}"></audio>`;
  return value;
}
"""


def run_browser(body: str) -> None:
    script = f"const ROOT = {json.dumps(str(ROOT))};\n" + HARNESS
    script += "\n(async () => {\n" + body + "\n})().catch(error => {console.error(error); process.exit(1);});"
    subprocess.run(["node", "-e", script], check=True, timeout=15, cwd=ROOT)


def test_mixed_selection_preserves_every_document_and_defers_document_uploads():
    run_browser(r"""
const ui = chat();
sandbox.fetch = async (url, options) => { requests.push(url); return {ok:true, json:async()=>({ok:true,images:[{url:'/uploads/photo.jpg',filename:'photo.jpg'}]})}; };
await ui._attachMultipleFiles([file('a.pdf','application/pdf'),file('photo.jpg','image/jpeg'),file('meeting.wav','audio/wav'),file('notes.md','text/markdown'),file('a.pdf','application/pdf')]);
assert.deepEqual(Array.from(ui.attachedDocuments, item => item.file.name), ['a.pdf','meeting.wav','notes.md','a.pdf']);
assert.equal(new Set(ui.attachedDocuments.map(item => item.uploadId)).size, 4);
assert.deepEqual(requests, ['/api/upload-images']);
assert.equal(ui.attachedImages.length, 1);
assert.equal(ui.imageAttachmentAction, 'analyze');
assert.equal(ui.filePreviewContainer.children.length, 4);
assert.equal(ui.filePreviewContainer.children[3].children[0].children[0].textContent, 'Source 4: a.pdf');
""")


def test_send_uploads_every_source_once_and_persists_document_order():
    run_browser(r"""
const ui = chat();
await ui._attachMultipleFiles([file('a.pdf'),file('notes.txt'),file('audio.wav')]);
assert.equal(requests.length,0);
await ui.sendMessage();
assert.deepEqual(requests.map(item=>item.url), ['/api/upload-pdf','/api/upload-text','/api/upload-audio']);
assert.ok(requests.every(item=>item.body.entries.mode==='cloud'));
assert.equal(sent.length,1);
assert.equal(sent[0][4],null);
assert.deepEqual(Array.from(sent[0][5],item=>item.filename),['a.pdf','notes.txt','audio.wav']);
assert.equal(ui.attachedDocuments.length,0);
assert.equal(ui.inputField.value,'');
assert.equal(revoked.length,1);
assert.match(ui.messagesContainer.children[0].innerHTML,/Source 2: notes.txt/);
""")


def test_normal_send_warms_tts_only_when_audio_is_enabled_and_send_succeeds():
    run_browser(r"""
const warmups=[];
sandbox.window.jarvisApp={audioEnabled:true,_warmTTS:mode=>warmups.push(mode)};
const enabled=chat();
await enabled.sendMessage();
assert.deepEqual(warmups,['cloud']);

sandbox.window.jarvisApp.audioEnabled=false;
const disabled=chat();
await disabled.sendMessage();
assert.deepEqual(warmups,['cloud']);

sandbox.window.jarvisApp.audioEnabled=true;
socket.connected=false;
const rejected=chat();
await rejected.sendMessage();
assert.deepEqual(warmups,['cloud']);
""")


def test_failed_upload_sends_nothing_and_retry_reuses_successes_and_ids():
    run_browser(r"""
const ui = chat();
await ui._attachMultipleFiles([file('a.pdf'),file('b.pdf'),file('notes.txt')]);
const ids = Array.from(ui.attachedDocuments,item=>item.uploadId);
let failure = true;
sandbox.fetch = async (url, options) => {
  requests.push({url,...options});
  if (failure && options.body.entries.file.name==='b.pdf') return {ok:false,json:async()=>({error:'Storage unavailable'})};
  return response(url.split('-').pop(),options.body.entries.file.name);
};
await ui.sendMessage();
assert.equal(sent.length,0);
assert.equal(requests.length,2);
assert.equal(ui.attachedDocuments.length,3);
assert.equal(ui.inputField.value,'Compare these sources');
assert.equal(ui.isProcessing,false);
failure=false;
await ui.sendMessage();
assert.equal(sent.length,1);
assert.deepEqual(requests.map(item=>item.body.entries.file.name),['a.pdf','b.pdf','b.pdf','notes.txt']);
assert.equal(requests[1].body.entries.upload_id,ids[1]);
assert.equal(requests[2].body.entries.upload_id,ids[1]);
""")


@pytest.mark.parametrize("interrupt", ["cancel", "mode", "conversation", "clear"])
def test_pending_upload_cannot_submit_after_context_changes(interrupt):
    run_browser(r"""
const ui=chat();
await ui.attachFile(file('a.pdf'));
const pending=deferred();
sandbox.fetch = async (url,options) => {requests.push({url,...options}); return pending.promise;};
const sending=ui.sendMessage();
await Promise.resolve();
await ui.sendMessage();
assert.equal(requests.length,1);
""" + {
        "cancel": "ui.cancelProcessing(); assert.equal(requests[0].signal.aborted,true);",
        "mode": "socket.mode='local'; ui.cancelAttachmentPreparation();",
        "conversation": "socket.conversationId='b';",
        "clear": "ui.clearChat();",
    }[interrupt] + r"""
pending.resolve(response('pdf','a.pdf'));
await sending;
assert.equal(sent.length,0);
assert.equal(ui.isProcessing,false);
assert.equal(ui._attachmentSend,null);
""")


def test_source_limits_reject_overflow_without_truncating_existing_draft():
    run_browser(r"""
const ui=chat();
await ui._attachMultipleFiles(Array.from({length:6},(_,i)=>file(`${i}.pdf`)));
await ui.attachFile(file('overflow.pdf'));
assert.equal(ui.attachedDocuments.length,6);
socket.mode='local';
ui._handleImageAttachmentsForMode('local');
assert.equal(ui.attachedDocuments.length,6);
await ui.sendMessage();
assert.equal(sent.length,0);
assert.equal(requests.length,0);
const other=chat();
await other._attachMultipleFiles([file('a.txt','text/plain',60000),file('b.txt','text/plain',60000)]);
assert.equal(other.attachedDocuments.length,0);
""")


def test_generation_mode_cannot_silently_discard_sources():
    run_browser(r"""
const ui=chat();
ui.pendingImageBatch=[{url:'/a.jpg',filename:'a.jpg'},{url:'/b.jpg',filename:'b.jpg'}];
ui._collectImageActionSettings=()=>({action:'video',settings:{}});
ui._confirmImageAction();
assert.equal(ui.pendingImageBatch.length,2);
assert.equal(ui.attachedImages.length,0);
ui.pendingImageBatch=null;
ui.attachedImages=[{url:'/a.jpg',filename:'a.jpg'}];
ui.imageAttachmentAction='image';
await ui.attachFile(file('notes.txt'));
assert.equal(ui.attachedDocuments.length,0);
assert.equal(ui.attachedImages.length,1);
""")


def test_image_action_modal_models_follow_provider_catalog_and_are_request_scoped():
    run_browser(r"""
const ui=chat();
sandbox.Option=class {constructor(text,value){this.textContent=text;this.value=value;}};
const makeSelect=value=>({value,children:[],add(item){this.children.push(item);},replaceChildren(){this.children=[];}});
const elements={
  imgActionImageProvider:makeSelect('openai'),
  imgActionImageModel:makeSelect(''),
  imgActionImageModelDesc:new Element(),
  imgActionImageSize:makeSelect('4K'),
  imgActionTransparent:Object.assign(new Element('input'),{checked:true,disabled:false}),
  imgActionTransparentDesc:new Element(),
};
sandbox.document.getElementById=id=>elements[id]||null;
sandbox.window.jarvisApp={_settingsData:{image_providers:{
  openai:{
    model:'gpt-image-2.5-flare',
    models:[
      {id:'gpt-image-2.5-flare',name:'GPT Image 2.5 Flare',capabilities:['transparent_background'],resolutions:['1K','2K','4K']},
      {id:'gpt-image-2',name:'GPT Image 2',capabilities:[]},
    ],
  },
  xai:{
    model:'grok-imagine-image-2.0',
    models:[
      {id:'grok-imagine-image-2.0',name:'Grok Imagine Image 2.0',capabilities:['quality_control'],resolutions:['1K','2K']},
    ],
  },
}}};
ui._updateImageProviderOptions(true);
assert.equal(elements.imgActionImageModel.value,'gpt-image-2.5-flare');
assert.equal(elements.imgActionTransparent.disabled,false);
elements.imgActionImageModel.value='gpt-image-2';
ui._updateImageProviderOptions();
assert.equal(elements.imgActionImageModel.value,'gpt-image-2');
assert.equal(elements.imgActionTransparent.disabled,true);
elements.imgActionImageProvider.value='xai';
elements.imgActionImageSize.value='4K';
ui._updateImageProviderOptions(true);
assert.equal(elements.imgActionImageModel.value,'grok-imagine-image-2.0');
assert.deepEqual(Array.from(elements.imgActionImageSize.children,item=>item.value),['1K','2K']);
assert.equal(elements.imgActionImageSize.value,'2K');
ui.imageActionModal={querySelector:()=>({value:'image'})};
const result=ui._collectImageActionSettings();
assert.equal(result.settings.provider,'xai');
assert.equal(result.settings.model,'grok-imagine-image-2.0');
assert.equal(result.settings.image_size,'2K');
assert.equal(requests.length,0);
""")


def test_video_action_modal_model_changes_clamp_dependent_controls():
    run_browser(r"""
const ui=chat();
sandbox.Option=class {constructor(text,value){this.textContent=text;this.value=value;}};
const makeSelect=value=>({value,children:[],add(item){this.children.push(item);},replaceChildren(){this.children=[];},appendChild(item){this.children.push(item);}});
const elements={
  imgActionVideoProvider:makeSelect('gemini'),
  imgActionVideoModel:makeSelect(''),
  imgActionVideoModelDesc:new Element(),
  imgActionVideoResolution:makeSelect('4k'),
  imgActionVideoRatio:makeSelect('4:3'),
  imgActionVideoDuration:Object.assign(new Element('input'),{value:'1'}),
  imgActionVideoDurationDesc:new Element(),
};
sandbox.document.getElementById=id=>elements[id]||null;
sandbox.window.jarvisApp={_settingsData:{video_providers:{gemini:{
  model:'veo-3.1-fast-generate-preview',
  models:[
      {id:'veo-3.1-fast-generate-preview',name:'Veo 3.1 Fast',resolutions:['720p','1080p','4k'],aspect_ratios:['16:9','9:16'],duration_seconds:{values:[4,6,8],by_resolution:{'1080p':[8],'4k':[8]}}},
    {id:'gemini-omni-flash-preview',name:'Gemini Omni Flash',resolutions:['720p'],aspect_ratios:['16:9','9:16'],duration_seconds:{min:3,max:10}},
  ],
}}}};
ui._updateVideoProviderOptions(true);
assert.equal(elements.imgActionVideoModel.value,'veo-3.1-fast-generate-preview');
assert.deepEqual(Array.from(elements.imgActionVideoResolution.children,item=>item.value),['720p','1080p','4k']);
assert.deepEqual(Array.from(elements.imgActionVideoRatio.children,item=>item.value),['16:9','9:16']);
assert.equal(elements.imgActionVideoRatio.value,'16:9');
assert.equal(elements.imgActionVideoDuration.value,'8');
assert.equal(elements.imgActionVideoDuration.step,'1');
elements.imgActionVideoModel.value='gemini-omni-flash-preview';
elements.imgActionVideoResolution.value='4k';
elements.imgActionVideoDuration.value='12';
ui._updateVideoProviderOptions();
assert.deepEqual(Array.from(elements.imgActionVideoResolution.children,item=>item.value),['720p']);
assert.equal(elements.imgActionVideoResolution.value,'720p');
assert.equal(elements.imgActionVideoDuration.value,'10');
assert.equal(elements.imgActionVideoDuration.min,'3');
assert.equal(elements.imgActionVideoDuration.max,'10');
ui.imageActionModal={querySelector:()=>({value:'video'})};
const result=ui._collectImageActionSettings();
assert.equal(result.settings.provider,'gemini');
assert.equal(result.settings.model,'gemini-omni-flash-preview');
assert.equal(result.settings.resolution,'720p');
assert.equal(result.settings.duration,10);
assert.equal(result.settings.aspect_ratio,'16:9');
assert.equal(requests.length,0);
""")


def test_video_action_reset_reclamps_default_duration_after_stale_4k():
    run_browser(r"""
const ui=chat();
sandbox.Option=class {constructor(text,value){this.textContent=text;this.value=value;}};
const makeSelect=value=>({
  value,
  children:[],
  get options(){return this.children;},
  add(item){this.children.push(item);},
  replaceChildren(){this.children=[];},
  appendChild(item){this.children.push(item);},
});
const elements={
  imgActionVideoProvider:makeSelect('gemini'),
  imgActionVideoModel:makeSelect('veo-3.1-fast-generate-preview'),
  imgActionVideoModelDesc:new Element(),
  imgActionVideoResolution:makeSelect('4k'),
  imgActionVideoRatio:makeSelect('16:9'),
  imgActionVideoDuration:Object.assign(new Element('input'),{value:'8'}),
  imgActionVideoDurationDesc:new Element(),
};
sandbox.document.getElementById=id=>elements[id]||null;
sandbox.window.jarvisApp={_settingsData:{
  video:{provider:{value:'gemini'}},
  video_providers:{gemini:{
    model:'veo-3.1-fast-generate-preview',
    models:[
      {id:'veo-3.1-fast-generate-preview',name:'Veo 3.1 Fast',resolutions:['720p','1080p','4k'],aspect_ratios:['16:9','9:16'],duration_seconds:{values:[4,6,8],by_resolution:{'1080p':[8],'4k':[8]}}},
    ],
  }},
}};
ui._resetImageActionOptions();
assert.equal(elements.imgActionVideoResolution.value,'720p');
assert.equal(elements.imgActionVideoDuration.value,'4');
assert.equal(elements.imgActionVideoDuration.step,'2');
assert.equal(requests.length,0);
""")


def test_text_only_chat_only_sends_durable_sources_but_pdf_is_blocked():
    run_browser(r"""
const ui=chat();
ui.chatOnlyEnabled=true;
await ui.attachFile(file('notes.txt'));
await ui.sendMessage();
assert.equal(sent.length,1);
assert.equal(sent[0][2].tool_policy,'none');
assert.equal(sent[0][5][0].kind,'text');
const other=chat();
other.chatOnlyEnabled=true;
await other.attachFile(file('a.pdf'));
await other.sendMessage();
assert.equal(sent.length,1);
""")


def test_remove_and_clear_revoke_each_audio_preview_and_renumber_sources():
    run_browser(r"""
const ui=chat();
await ui._attachMultipleFiles([file('one.wav'),file('two.wav'),file('notes.txt')]);
const first=ui.attachedDocuments[0], second=ui.attachedDocuments[1];
const firstUrl=first.previewUrl, secondUrl=second.previewUrl;
ui._removeAttachedDocument(first);
assert.deepEqual(revoked,[firstUrl]);
assert.equal(ui.filePreviewContainer.children[0].children[0].children[0].textContent,'Source 1: two.wav');
assert.equal(second.previewUrl,secondUrl);
ui.clearChat();
assert.deepEqual(revoked,[firstUrl,secondUrl]);
assert.equal(ui.attachedDocuments.length,0);
""")


def test_reload_renders_all_names_and_all_audio_sources_without_duplicate_labels():
    run_browser(r"""
const ui=chat();
const app=Object.create(JarvisApp.prototype);
Object.assign(app,{chat:ui,socket,_updateActiveConversation(){},_updateConvIdBadge(){},_loadConversationHistory(){}});
const attachments=[{kind:'pdf',filename:'same.pdf',stash_ref:'stash://a/one'},{kind:'audio',filename:'one.wav',stash_ref:'stash://a/two'},{kind:'text',filename:'<note>.txt',stash_ref:'stash://a/three'},{kind:'audio',filename:'two.wav',stash_ref:'stash://a/four'},{kind:'pdf',filename:'same.pdf',stash_ref:'stash://a/five'}];
await app._displayLoadedConversation({id:'saved',messages:[{role:'user',content:'Compare all',data:{attachments}}]});
const html=ui.messagesContainer.children[0].innerHTML;
assert.match(html,/Source 1: same.pdf/);
assert.match(html,/Source 3: &lt;note&gt;.txt/);
assert.match(html,/Source 5: same.pdf/);
assert.equal((html.match(/<audio /g)||[]).length,2);
assert.ok(html.includes('stash://a/two') && html.includes('stash://a/four'));
""")


def test_socket_keeps_the_ordered_bundle_and_existing_image_contract():
    run_browser(r"""
const client=new JarvisSocket();
const events=[];
Object.assign(client,{connected:true,mode:'local',conversationId:'thread',socket:{emit:(...args)=>events.push(args)}});
const attachments=[{kind:'pdf',stash_ref:'stash://a/one'},{kind:'text',stash_ref:'stash://a/two'}];
const image={action:'analyze',images:[{url:'/a.jpg',filename:'a.jpg'}]};
assert.equal(client.sendMessage('Compare',image,null,false,null,attachments),true);
assert.equal(events[0][0],'chat:send');
assert.equal(events[0][1].attachments,attachments);
assert.equal(events[0][1].image,image);
assert.equal(events[0][1].mode,'local');
""")


def test_image_upload_cannot_attach_or_show_modal_in_a_new_conversation():
    run_browser(r"""
const ui=chat();
const pending=deferred();
sandbox.fetch=async(url,options)=>{requests.push({url,...options});return pending.promise;};
const selection=ui.attachFile(file('photo.jpg','image/jpeg'));
await Promise.resolve();
assert.equal(ui.isProcessing,true);
await ui.sendMessage();
assert.equal(sent.length,0);
ui.clearChat();
assert.equal(requests[0].signal.aborted,true);
socket.conversationId='new-thread';
pending.resolve({ok:true,json:async()=>({ok:true,images:[{url:'/a.jpg',filename:'a.jpg'}]})});
await selection;
assert.equal(ui.attachedImages.length,0);
assert.equal(ui.pendingImageBatch,null);
assert.equal(ui.isProcessing,false);
""")


def test_late_model_settings_cannot_restore_a_cancelled_image_modal():
    run_browser(r"""
const ui=chat();
ui.imageActionModal=new Element();
const settings=deferred();
sandbox.window.jarvisApp={_ensureSettingsData:()=>settings.promise};
const showing=ChatUI.prototype._showImageActionModal.call(ui,[{url:'/a.jpg',filename:'a.jpg'}]);
ui.cancelAttachmentPreparation();
settings.resolve();
await showing;
assert.equal(ui.pendingImageBatch,null);
""")


def test_incomplete_image_batch_is_explicit_and_does_not_silently_select_a_subset():
    run_browser(r"""
const ui=chat();
sandbox.fetch=async()=>({ok:true,json:async()=>({ok:true,images:[{url:'/a.jpg',filename:'a.jpg'}],errors:['b.jpg: invalid image']})});
await ui._attachMultipleFiles([file('a.jpg','image/jpeg'),file('b.jpg','image/jpeg')]);
assert.equal(ui.attachedImages.length,0);
assert.equal(ui.pendingImageBatch,null);
assert.ok(notices.some(item=>item[0].includes('b.jpg: invalid image')));
""")


def test_editing_a_draft_while_uploading_preserves_it_without_stale_submission():
    run_browser(r"""
const ui=chat();
await ui.attachFile(file('notes.txt'));
const pending=deferred();
sandbox.fetch=async()=>pending.promise;
const sending=ui.sendMessage();
ui.inputField.value='A revised request';
pending.resolve(response('text','notes.txt'));
await sending;
assert.equal(sent.length,0);
assert.equal(ui.inputField.value,'A revised request');
assert.equal(ui.attachedDocuments.length,1);
assert.ok(ui.attachedDocuments[0].attachment);
assert.equal(ui.isProcessing,false);
""")


def test_selection_cannot_unlock_an_inflight_server_request():
    run_browser(r"""
const ui=chat();
ui.isProcessing=true;
ui.currentMessageId='running';
await ui.attachFile(file('a.jpg','image/jpeg'));
assert.equal(requests.length,0);
assert.equal(ui.isProcessing,true);
assert.equal(ui.currentMessageId,'running');
""")


def test_failed_mixed_image_bundle_keeps_selected_files_and_retry_submits_every_source():
    run_browser(r"""
const ui=chat();
ui.imagePreviewStrip=new Element();
ui.imagePreviewContainer=new Element();
const imageFile=file('photo.jpg','image/jpeg');
sandbox.fetch=async()=>({ok:false,json:async()=>({error:'Image upload unavailable'})});
await ui._attachMultipleFiles([file('report.pdf'),imageFile]);
assert.equal(ui.attachedDocuments.length,1);
assert.equal(ui.pendingImageFiles.length,1);
assert.equal(ui.pendingImageFiles[0].file,imageFile);
assert.equal(ui.imagePreviewContainer.style.display,'block');
assert.ok(ui.imagePreviewStrip.children.some(item=>item.textContent==='Retry image upload'));
assert.equal(ui.isProcessing,false);
await ui.sendMessage();
assert.equal(sent.length,0);
sandbox.fetch=async(url,options)=>{
  requests.push({url,...options});
  if(url==='/api/upload-images') return {ok:true,json:async()=>({ok:true,images:[{url:'/photo.jpg',filename:'photo.jpg'}]})};
  return response('pdf','report.pdf');
};
await ui._retryPendingImages();
assert.equal(requests[0].body.entries.images,imageFile);
assert.equal(ui.pendingImageFiles.length,0);
assert.equal(ui.attachedImages.length,1);
assert.equal(ui.attachedDocuments.length,1);
await ui.sendMessage();
assert.equal(sent.length,1);
assert.equal(sent[0][1].images.length,1);
assert.equal(sent[0][5].length,1);
assert.equal(revoked.length,1);
""")


def test_removing_failed_image_is_explicit_and_allows_remaining_document_send():
    run_browser(r"""
const ui=chat();
sandbox.fetch=async()=>({ok:false,json:async()=>({error:'Upload failed'})});
await ui._attachMultipleFiles([file('notes.txt'),file('photo.jpg','image/jpeg')]);
const pending=ui.pendingImageFiles[0];
await ui.sendMessage();
assert.equal(sent.length,0);
ui._removePendingImage(pending);
assert.deepEqual(revoked,[pending.previewUrl]);
sandbox.fetch=async()=>response('text','notes.txt');
await ui.sendMessage();
assert.equal(sent.length,1);
assert.equal(sent[0][1],null);
assert.equal(sent[0][5][0].filename,'notes.txt');
""")


def test_pending_images_count_toward_mode_limit_and_clear_revokes_all():
    run_browser(r"""
const ui=chat();
sandbox.fetch=async()=>({ok:false,json:async()=>({error:'Upload failed'})});
await ui._attachMultipleFiles([file('report.pdf'),file('one.jpg','image/jpeg'),file('two.jpg','image/jpeg')]);
socket.mode='local';
ui.cancelAttachmentPreparation();
ui._handleImageAttachmentsForMode('local');
const count=requests.length;
await ui._retryPendingImages();
assert.equal(requests.length,count);
assert.equal(ui.pendingImageFiles.length,2);
assert.ok(notices.some(item=>item[0].includes('Maximum 2 sources')));
ui.clearChat();
assert.equal(ui.pendingImageFiles.length,0);
assert.equal(revoked.length,2);
""")


@pytest.mark.parametrize("interrupt", ["cancel", "mode"])
def test_image_files_survive_cancellation_while_modal_settings_load(interrupt):
    run_browser(r"""
const ui=chat();
ui.imageActionModal=new Element();
ui.imagePreviewStrip=new Element();
ui.imagePreviewContainer=new Element();
ui._showImageActionModal=ChatUI.prototype._showImageActionModal;
const settings=deferred(), entered=deferred();
sandbox.window.jarvisApp={_ensureSettingsData:()=>{entered.resolve();return settings.promise;}};
sandbox.fetch=async()=>({ok:true,json:async()=>({ok:true,images:[{url:'/photo.jpg',filename:'photo.jpg'}]})});
const selectedFile=file('photo.jpg','image/jpeg');
const selection=ui.attachFile(selectedFile);
await entered.promise;
const pendingItem=ui.pendingImageFiles[0];
assert.equal(pendingItem.file,selectedFile);
""" + {
        "cancel": "ui.cancelProcessing();",
        "mode": "socket.mode='local'; ui.cancelAttachmentPreparation();",
    }[interrupt] + r"""
assert.equal(ui.pendingImageFiles[0],pendingItem);
assert.equal(revoked.length,0);
settings.resolve();
await selection;
assert.equal(ui.pendingImageBatch,null);
assert.equal(ui.attachedImages.length,0);
assert.equal(ui.pendingImageFiles[0].file,selectedFile);
assert.ok(ui.imagePreviewStrip.children.some(item=>item.textContent==='Retry image upload'));
ui._showImageActionModal=async uploads=>{ui.pendingImageBatch=uploads;};
await ui._retryPendingImages();
assert.equal(ui.pendingImageFiles[0].file,selectedFile);
ui._collectImageActionSettings=()=>({action:'analyze',settings:{}});
ui._confirmImageAction();
assert.equal(ui.pendingImageFiles.length,0);
assert.equal(ui.attachedImages.length,1);
assert.deepEqual(revoked,[pendingItem.previewUrl]);
""")


@pytest.mark.parametrize("target", ["new", "saved", "mode"])
def test_deferred_canvas_import_cannot_attach_into_changed_context(target):
    run_browser(r"""
const ui=chat();
ui.refreshContextWindow=()=>{};
const app=Object.create(JarvisApp.prototype);
Object.assign(app,{chat:ui,socket,_updateActiveConversation(){},_updateConvIdBadge(){}});
sandbox.window.location={href:'https://jarvis.example/?media_handoff=image&media_filename=photo.jpg'};
const pending=deferred();
sandbox.fetch=async()=>pending.promise;
let imported=0;
ui.attachImportedImage=async()=>{imported+=1;};
const loading=app._consumeMediaHandoff();
""" + {
        "new": "app._startNewChat();",
        "saved": "socket.conversationId='saved'; ui.clearChat();",
        "mode": "socket.mode='local'; ui.cancelAttachmentPreparation();",
    }[target] + r"""
pending.resolve({ok:true,json:async()=>({ok:true,url:'/photo.jpg',filename:'photo.jpg'})});
await loading;
assert.equal(imported,0);
assert.equal(ui.attachedImages.length,0);
assert.equal(ui.pendingImageBatch,null);
""")


def test_persisted_pdf_and_text_sources_have_safe_open_and_download_links():
    run_browser(r"""
const ui=chat();
ui.addUserMessage('Review',null,'',[
  {kind:'pdf',filename:'report.pdf',stash_ref:'stash://source_a/pdf'},
  {kind:'text',filename:'<note>".txt',stash_ref:'stash://source_b/text'},
  {kind:'text',filename:'invalid.txt',stash_ref:'javascript:alert(1)'}
]);
const html=ui.messagesContainer.children[0].innerHTML;
assert.match(html,/href="\/api\/stash\/source_a\/pdf\?mode=cloud" target="_blank" rel="noopener noreferrer">Source 1: report.pdf<\/a>/);
assert.match(html,/href="\/api\/stash\/source_b\/text\?mode=cloud" download="&lt;note&gt;&quot;.txt"/);
assert.ok(html.includes('Source 3: invalid.txt'));
assert.equal(html.includes('javascript:'),false);
assert.equal((html.match(/download=/g)||[]).length,2);
""")


def test_failed_mixed_image_stash_preparation_restores_image_retry_payload():
    run_browser(r"""
const ui=chat();
const listeners={};
socket.on=(name,callback)=>{listeners[name]=callback;};
ui.addErrorMessage=()=>{};
ui._clearPendingToolsForMessage=()=>{};
ui.pendingVisionRetryPayload={action:'analyze',settings:{},images:[{url:'/photo.jpg',filename:'photo.jpg'}]};
ui._setupSocketListeners();
listeners.error({error:'Could not prepare image sources',error_code:'image_bundle_stash_failed'});
assert.equal(ui.attachedImages.length,1);
assert.equal(ui.attachedImages[0].filename,'photo.jpg');
assert.equal(ui.isProcessing,false);
assert.ok(notices.some(item=>item[0].includes('retry preparing')));
""")


def test_saved_source_links_and_audio_keep_original_mode_after_ui_switch():
    run_browser(r"""
const ui=chat();
ui._normalizeAudioAttachment=ChatUI.prototype._normalizeAudioAttachment;
ui._renderAudioPlayerHtml=ChatUI.prototype._renderAudioPlayerHtml;
const app=Object.create(JarvisApp.prototype);
Object.assign(app,{chat:ui,socket,_updateActiveConversation(){},_updateConvIdBadge(){},_loadConversationHistory(){}});
socket.mode='local';
await app._displayLoadedConversation({id:'saved-cloud',messages:[{role:'user',content:'Review sources',data:{attachments:[
  {kind:'pdf',filename:'report.pdf',stash_ref:'stash://cloud_space/pdf',mode:'cloud'},
  {kind:'text',filename:'notes.txt',stash_ref:'stash://cloud_space/text',mode:'cloud'},
  {kind:'audio',filename:'notes.wav',stash_ref:'stash://cloud_space/audio',mode:'cloud'}
]}}]});
const html=ui.messagesContainer.children[0].innerHTML;
assert.ok(html.includes('/api/stash/cloud_space/pdf?mode=cloud'));
assert.ok(html.includes('/api/stash/cloud_space/text?mode=cloud'));
assert.ok(html.includes('/api/stash/cloud_space/audio?mode=cloud'));
assert.equal(html.includes('?mode=local'),false);
assert.equal(ui._sourceAttachmentUrl({kind:'text',stash_ref:'stash://old/source'}),'/api/stash/old/source?mode=local');
""")


def test_document_uploads_tag_mode_and_reprepare_in_new_mode_on_retry():
    run_browser(r"""
const ui=chat();
await ui.attachFile(file('report.pdf'));
const selected=ui.attachedDocuments[0];
const cloud=await ui._uploadAttachedDocument(selected,ui._attachmentContext());
assert.equal(cloud.mode,'cloud');
const again=await ui._uploadAttachedDocument(selected,ui._attachmentContext());
assert.equal(again,cloud);
assert.equal(requests.length,1);
socket.mode='local';
const local=await ui._uploadAttachedDocument(selected,ui._attachmentContext());
assert.equal(local.mode,'local');
assert.equal(requests.length,2);
assert.equal(requests[0].body.entries.upload_id,requests[1].body.entries.upload_id);
assert.equal(requests[1].body.entries.mode,'local');
""")


def test_canvas_video_handoff_uses_normal_modal_with_video_preselected():
    run_browser(r"""
const ui=chat();
ui.refreshContextWindow=()=>{};
ui.imageActionModal=new Element();
const videoRadio={checked:false};
ui.imageActionModal.querySelector=selector=>selector.includes('[value="video"]')?videoRadio:null;
ui._showImageActionModal=ChatUI.prototype._showImageActionModal;
ui._resetImageActionOptions=()=>{};
ui._updateImageActionOptions=()=>{};
const app=Object.create(JarvisApp.prototype);
Object.assign(app,{chat:ui,socket,_updateActiveConversation(){},_updateConvIdBadge(){}});
sandbox.window.location={href:'https://jarvis.example/?media_handoff=image&media_filename=photo.jpg&media_action=video'};
sandbox.fetch=async(url,options)=>{requests.push({url,...options});return {ok:true,json:async()=>({ok:true,url:'/photo.jpg',filename:'photo.jpg'})};};
await app._consumeMediaHandoff();
assert.equal(videoRadio.checked,true);
assert.equal(ui.pendingImageBatch[0].filename,'photo.jpg');
assert.equal(ui.attachedImages.length,0);
assert.equal(sent.length,0);
assert.deepEqual(requests.map(item=>item.url),['/api/media-handoff/import']);
""")


def test_conversation_load_blocks_send_until_target_is_displayed():
    run_browser(r"""
const ui=chat();
await ui.attachFile(file('private-a.pdf'));
const navigation=[];
socket.emit=(...args)=>navigation.push(args);
const app=Object.create(JarvisApp.prototype);
Object.assign(app,{chat:ui,socket,_updateActiveConversation(){},_updateConvIdBadge(){},_loadConversationHistory(){}});
app.loadConversation('b');
await ui.sendMessage();
assert.equal(sent.length,0,'A source must not be submitted while B is loading');
assert.equal(requests.length,0,'pending navigation must not start document uploads');
assert.equal(ui.attachedDocuments[0].file.name,'private-a.pdf','preserve sources until load succeeds');
// JarvisSocket updates its id before delivering conversationLoaded to App.
socket.conversationId='b';
await app._displayLoadedConversation({id:'b',messages:[]});
assert.equal(ui.attachedDocuments.length,0);
ui.inputField.value='A question for B';
await ui.sendMessage();
assert.equal(sent.length,1);
assert.equal(sent[0][5].length,0,'B must not receive A attachments');
""")


@pytest.mark.parametrize("origin", ["a", None])
def test_successful_switch_clears_all_settled_source_state_and_notifies(origin):
    run_browser(f"socket.conversationId={json.dumps(origin)};\n" + r"""
const ui=chat();
await ui._attachMultipleFiles([file('a.pdf'),file('audio.wav')]);
ui.attachedImages=[{url:'/ready.jpg',filename:'ready.jpg'}];
const pending={file:file('pending.jpg','image/jpeg'),previewUrl:'blob:pending-switch'};
ui.pendingImageFiles=[pending];
ui.pendingImageBatch=[{url:'/pending.jpg',filename:'pending.jpg'}];
ui.pendingVisionRetryPayload={action:'analyze',images:[{url:'/old.jpg',filename:'old.jpg'}]};
socket.emit=()=>{};
const app=Object.create(JarvisApp.prototype);
Object.assign(app,{chat:ui,socket,_updateActiveConversation(){},_updateConvIdBadge(){},_loadConversationHistory(){}});
app.loadConversation('b');
socket.conversationId='b';
await app._displayLoadedConversation({id:'b',messages:[]});
assert.equal(ui.attachedDocuments.length,0);
assert.equal(ui.attachedImages.length,0);
assert.equal(ui.pendingImageFiles.length,0);
assert.equal(ui.pendingImageBatch,null);
assert.equal(ui.pendingVisionRetryPayload,null);
assert.ok(revoked.includes(pending.previewUrl));
assert.equal(revoked.length,2);
assert.ok(notices.some(item=>/sources.*cleared|cleared.*sources/i.test(item[0])),'successful removal needs a concise notice');
""")


def test_same_conversation_refresh_preserves_settled_sources_and_draft():
    run_browser(r"""
const ui=chat();
await ui.attachFile(file('a.wav'));
const original=ui.attachedDocuments[0];
ui.attachedImages=[{url:'/ready.jpg',filename:'ready.jpg'}];
socket.emit=()=>{};
const app=Object.create(JarvisApp.prototype);
Object.assign(app,{chat:ui,socket,_updateActiveConversation(){},_updateConvIdBadge(){},_loadConversationHistory(){}});
app.loadConversation('a');
socket.conversationId='a';
await app._displayLoadedConversation({id:'a',messages:[]});
assert.equal(ui.attachedDocuments[0],original);
assert.equal(ui.attachedImages.length,1);
assert.equal(ui.inputField.value,'Compare these sources');
assert.equal(revoked.length,0);
assert.equal(ui._conversationLoadPending,false);
""")


@pytest.mark.parametrize("destination", ["new", "c"])
def test_late_load_response_cannot_change_the_new_composer_owner(destination):
    run_browser(r"""
const ui=chat();
ui.refreshContextWindow=()=>{};
await ui.attachFile(file('a.pdf'));
socket.emit=()=>{};
const app=Object.create(JarvisApp.prototype);
Object.assign(app,{chat:ui,socket,_updateActiveConversation(){},_updateConvIdBadge(){},_loadConversationHistory(){}});
app.loadConversation('b');
""" + {
        "new": "app._startNewChat(); await ui.attachFile(file('new.pdf'));",
        "c": "app.loadConversation('c'); socket.conversationId='c'; await app._displayLoadedConversation({id:'c',messages:[]}); await ui.attachFile(file('c.pdf'));",
    }[destination] + r"""
const currentSource=ui.attachedDocuments[0];
const currentConversation=socket.conversationId;
// The Socket wrapper updates its ID before App can reject the stale response.
socket.conversationId='b';
await app._displayLoadedConversation({id:'b',messages:[]});
assert.equal(socket.conversationId,currentConversation);
assert.equal(ui.attachedDocuments[0],currentSource);
assert.equal(ui._conversationLoadPending,false);
await ui.sendMessage();
assert.equal(sent.length,1);
assert.equal(sent[0][5][0].filename,currentSource.file.name);
""")


def test_navigation_aborts_inflight_upload_but_failed_load_keeps_retryable_sources():
    run_browser(r"""
const ui=chat();
await ui.attachFile(file('a.pdf'));
const original=ui.attachedDocuments[0];
const pending=deferred();
sandbox.fetch=async(url,options)=>{requests.push({url,...options});return pending.promise;};
const sending=ui.sendMessage();
await Promise.resolve();
socket.emit=()=>{};
const app=Object.create(JarvisApp.prototype);
Object.assign(app,{chat:ui,socket});
app.loadConversation('missing');
assert.equal(requests[0].signal.aborted,true);
assert.equal(ui.sendBtn.disabled,true);
pending.resolve(response('pdf','a.pdf'));
await sending;
assert.equal(sent.length,0);
assert.equal(ui.attachedDocuments[0],original);
assert.equal(ui._conversationLoadPending,true);
app._releaseConversationLoad();
assert.equal(ui.sendBtn.disabled,false);
sandbox.fetch=async(url,options)=>{requests.push({url,...options});return response('pdf','a.pdf');};
await ui.sendMessage();
assert.equal(sent.length,1);
assert.equal(requests.length,1,'a completed upload may be reused after navigation fails');
assert.equal(sent[0][5][0],original.attachment);
""")


def test_superseded_response_keeps_send_locked_until_requested_target_loads():
    run_browser(r"""
const ui=chat();
await ui.attachFile(file('a.pdf'));
socket.emit=()=>{};
const app=Object.create(JarvisApp.prototype);
Object.assign(app,{chat:ui,socket,_updateActiveConversation(){},_updateConvIdBadge(){},_loadConversationHistory(){}});
app.loadConversation('b');
app.loadConversation('c');
socket.conversationId='b';
await app._displayLoadedConversation({id:'b',messages:[]});
assert.equal(socket.conversationId,'a');
assert.equal(ui.attachedDocuments[0].file.name,'a.pdf');
assert.equal(ui._conversationLoadPending,true);
await ui.sendMessage();
assert.equal(sent.length,0);
socket.conversationId='c';
await app._displayLoadedConversation({id:'c',messages:[]});
assert.equal(socket.conversationId,'c');
assert.equal(ui.attachedDocuments.length,0);
assert.equal(ui._conversationLoadPending,false);
""")


def test_created_conversation_can_reload_without_clearing_its_sources():
    run_browser(r"""
const ui=chat();
ui.refreshContextWindow=()=>{};
const listeners={};
socket.on=(name,callback)=>{listeners[name]=callback;};
const app=Object.create(JarvisApp.prototype);
Object.assign(app,{chat:ui,socket,_completedResponseIds:new Set(),_cancelStatusTTS(){},_updateActiveConversation(){},_updateConvIdBadge(){},_loadConversationHistory(){}});
app._setupSocketListeners();
app._startNewChat();
listeners.conversationCreated({conversation_id:'created'});
await ui.attachFile(file('created.pdf'));
const original=ui.attachedDocuments[0];
await app._displayLoadedConversation({id:'created',messages:[{role:'user',content:'saved question'}]});
assert.equal(socket.conversationId,'created');
assert.equal(ui.attachedDocuments[0],original);
assert.match(ui.messagesContainer.children[0].innerHTML,/saved question/);
""")


def test_stale_load_error_cannot_release_the_current_navigation_lock():
    run_browser(r"""
const ui=chat();
await ui.attachFile(file('a.pdf'));
const listeners={};
socket.on=(name,callback)=>{listeners[name]=callback;};
socket.emit=()=>{};
const app=Object.create(JarvisApp.prototype);
Object.assign(app,{chat:ui,socket,_completedResponseIds:new Set(),_cancelStatusTTS(){},_updateActiveConversation(){},_updateConvIdBadge(){},_loadConversationHistory(){}});
app._setupSocketListeners();
app.loadConversation('missing-b');
app.loadConversation('c');
listeners.error({error:'Conversation not found',error_code:'conversation_not_found',conversation_id:'missing-b'});
assert.equal(ui._conversationLoadPending,true);
assert.equal(ui.attachedDocuments[0].file.name,'a.pdf');
await ui.sendMessage();
assert.equal(sent.length,0);
socket.conversationId='c';
await app._displayLoadedConversation({id:'c',messages:[]});
assert.equal(ui._conversationLoadPending,false);
assert.equal(ui.attachedDocuments.length,0);
""")


def test_failed_conversation_load_preserves_sources_and_explicitly_unblocks_send():
    run_browser(r"""
const ui=chat();
await ui.attachFile(file('a.pdf'));
const original=ui.attachedDocuments[0];
const listeners={};
socket.on=(name,callback)=>{listeners[name]=callback;};
socket.emit=()=>{};
const app=Object.create(JarvisApp.prototype);
Object.assign(app,{chat:ui,socket,_completedResponseIds:new Set(),_cancelStatusTTS(){},_updateActiveConversation(){},_updateConvIdBadge(){},_loadConversationHistory(){}});
app._setupSocketListeners();
app.loadConversation('missing');
await ui.sendMessage();
assert.equal(sent.length,0);
listeners.error({error:'Conversation not found',conversation_id:'missing'});
assert.equal(ui.attachedDocuments[0],original);
assert.equal(socket.conversationId,'a');
assert.equal(ui._conversationLoadPending,false);
await ui.sendMessage();
assert.equal(sent.length,1);
assert.equal(sent[0][5][0].filename,'a.pdf');
""")


def test_new_chat_clears_sources_with_notice_and_pending_upload_cannot_resend():
    run_browser(r"""
const ui=chat();
ui.refreshContextWindow=()=>{};
await ui.attachFile(file('a.wav'));
const pending=deferred();
sandbox.fetch=async(url,options)=>{requests.push({url,...options});return pending.promise;};
const sending=ui.sendMessage();
await Promise.resolve();
const app=Object.create(JarvisApp.prototype);
Object.assign(app,{chat:ui,socket,_updateActiveConversation(){},_updateConvIdBadge(){}});
app._startNewChat();
assert.equal(requests[0].signal.aborted,true);
assert.equal(ui.attachedDocuments.length,0);
assert.equal(revoked.length,1);
assert.ok(notices.some(item=>/sources.*cleared|cleared.*sources/i.test(item[0])));
pending.resolve(response('audio','a.wav'));
await sending;
assert.equal(sent.length,0);
assert.equal(socket.conversationId,null);
assert.equal(ui._conversationLoadPending,false);
""")
