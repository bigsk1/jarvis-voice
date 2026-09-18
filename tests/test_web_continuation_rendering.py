"""Late live/history content stays DOM text and cannot consume foreground actions."""

import json

import pytest
from test_web_assistant_message_rendering import run_message_browser

DOM = r"""
// Shipped scripts, including the continuation renderer, are loaded by the harness.
// Prohibit HTML fragments; only a single validated entity may reach the decoder.
// Inspect actual DOM writes through the production entry point.
const oldCreate = sandbox.document.createElement;
sandbox.document.createElement = tag => { const el = oldCreate(); el.tag = tag; return el; };
function descendants(el) { return el.children.flatMap(child => [child, ...descendants(child)]); }
function visible(el) { return el.textContent + el.children.map(visible).join(''); }
Element.prototype.querySelectorAll = function(selector) {
  const classes = selector.split('.').slice(1);
  return descendants(this).filter(el => classes.length && classes.every(c => el.classList.contains(c)));
};
Element.prototype.querySelector = function(selector) { return this.querySelectorAll(selector)[0] || null; };
Element.prototype.remove = function() {
  if (this.parentElement) this.parentElement.children = this.parentElement.children.filter(child => child !== this);
};
Element.prototype.setAttribute = function(key, value) { this[key] = value; };
Object.defineProperty(Element.prototype, 'innerHTML', {
  get() { return this._html; },
  set(value) {
    if (this.tag === 'textarea' && /^&(?:[a-z][a-z0-9]*|#(?:[0-9]+|x[0-9a-f]+));$/i.test(value)) {
      const named = {'&amp;':'&','&lt;':'<','&gt;':'>','&quot;':'"','&apos;':"'",'&copy;':'©'};
      this.value = value.startsWith('&#')
        ? String.fromCodePoint(parseInt(value.slice(value[2].toLowerCase() === 'x' ? 3 : 2, -1), value[2].toLowerCase() === 'x' ? 16 : 10))
        : named[value] || value;
      return;
    }
    throw new Error('Untrusted late path reached innerHTML: ' + value);
  }
});
vm.runInContext(fs.readFileSync(clientPath + '/vendor/marked.min.js', 'utf8'), sandbox);
sandbox.window.marked = sandbox.marked;
function lateData(payload, form) {
  if (form === 'live') return {message_id:'late', conversation_id:'thread', data:payload};
  if (form === 'saved') return {...payload, _kind:'continuation', _web_message_id:'late'};
  if (form === 'nested') return {data:{...payload, _continuation_id:'late', _web_message_id:'late'}};
  if (form === 'object_nested') return {data:{message_id:'late', data:{...payload, _kind:'continuation'}}};
  if (form === 'object_marker') return {_kind:'continuation', data:{...payload, _web_message_id:'late'}};
  return {content:'Object answer', data:{...payload, _kind:'continuation', _web_message_id:'late'}};
}
"""


@pytest.mark.parametrize('form', ['live', 'saved', 'nested', 'object', 'object_nested', 'object_marker'])
@pytest.mark.parametrize('marked', [True, False])
def test_html_links_and_artifact_attributes_are_inert_in_all_late_shapes(form, marked):
    run_message_browser(DOM + f"\nconst form={json.dumps(form)}, useMarked={json.dumps(marked)};\n" + r"""
if (!useMarked) sandbox.window.marked = undefined;
const ui = chat();
const attack = '<img src=x onerror=alert(1)> <svg onload=alert(2)>\n\n'
  + '[run](javascript:alert%281%29) [entity](java&#x73;cript:alert%281%29) '
  + '[data](data:text/html,attack) [encoded](&#106;avascript:alert%281%29)';
const ref = 'stash://custom space/pic.png" onerror="alert(1)';
const videoRef = "stash://custom space/vid.mp4' onclick='alert(2)";
const payload = {fixture:{stash_ref:ref, filename:'picture.png'},
  other:[{data:{saved:{stash_ref:videoRef,filename:'<svg onload=alert(3)>.mp4'}}}],
  generate_music:{filename:'sound.mp3', file_url:'/x.mp3" onerror="alert(4)'},
  raw_llm_response:attack};
const before = JSON.stringify(payload);
const data = lateData(payload, form);
if (form.startsWith('object')) ui.addAssistantMessage({...data, content:attack});
else ui.addAssistantMessage(attack, [], data, form === 'live' ? {late:true} : {});
const rendered = message(ui), all = descendants(rendered);
assert.equal(rendered.dataset.messageId, 'late');
assert.ok(ui._renderedMessageIds.has('assistant:late'));
assert.ok(!all.some(el => ['img','svg','script','iframe','audio','video'].includes(el.tag)));
assert.ok(visible(rendered).includes('<img src=x onerror=alert(1)>'));
const links = all.filter(el => el.tag === 'a');
assert.equal(links.length, 2);
assert.ok(links.every(el => el.href.startsWith('/stash/view/custom%20space/') && el.rel === 'noopener noreferrer'));
assert.ok(links.some(el => el.href.includes('%22%20onerror%3D%22')));
assert.ok(links.some(el => el.href.includes('%27%20onclick%3D%27')));
assert.equal(JSON.stringify(payload), before);
assert.ok(!effects.some(e => e === 'clear-actions' || e === 'hydrate' || Array.isArray(e)));
""")


def test_readable_markdown_and_valid_stash_links_survive():
    run_message_browser(DOM + r"""
const ui = chat();
const text = '# Finished\n\n**Ready** with *details* and ~~removed~~.\n\n'
  + '> A note\n\n1. First\n2. Second\n\n'
  + '| File | Status |\n| --- | --- |\n| Report | Done |\n\n'
  + '```html\n<img src=x onerror=alert(1)>\n```\n\n'
  + '[Report](stash://space_one/f_report) [Source](https://example.com/report?a=1&b=2)\n\n'
  + '![Preview](stash://space_one/f_image)';
ui.addAssistantMessage(text, [], {_kind:'continuation', fixture:{stash_ref:'stash://space_one/f_report', filename:'Report.pdf'}});
const all = descendants(message(ui));
for (const tag of ['h1','strong','em','del','blockquote','ol','li','table','thead','tbody','th','td','pre','code']) {
  assert.ok(all.some(el => el.tag === tag), tag);
}
assert.equal(all.find(el => el.tag === 'code').textContent, '<img src=x onerror=alert(1)>');
assert.ok(all.some(el => el.href === '/stash/view/space_one/f_report'));
assert.ok(all.some(el => el.href === '/stash/view/space_one/f_image'));
assert.ok(all.some(el => el.href === 'https://example.com/report?a=1&b=2'));
assert.ok(visible(message(ui)).includes('Report.pdf'));
""")


def test_invalid_stash_refs_are_not_truncated_or_reinterpreted():
    run_message_browser(DOM + r"""
const ui = chat();
ui.addAssistantMessage('No artifacts', [], {_kind:'continuation', results:[
  'stash://space/file/extra', 'stash://space/..', 'stash://../file',
  'stash://space/file\n', 'stash://space\\host/file', 'stash://space/\uD800'
]});
assert.equal(descendants(message(ui)).filter(el => el.tag === 'a').length, 0);
""")


def test_markdown_entities_decode_before_url_validation_but_artifacts_and_code_are_literal():
    run_message_browser(DOM + r"""
const ui = chat();
ui.addAssistantMessage('Tom &amp; Jerry &copy; &#65; \\*literal\\*\n\n'
  + '&lt;img src=x onerror=alert(1)&gt;\n\n'
  + '[Report](https://example.com/?a=1&amp;b=2) '
  + '[bad](java&#x73;cript:alert%281%29) [bad](javascript&#58;alert%281%29)\n\n'
  + '`&amp;`\n\n```text\n&amp;\n```', [], {_kind:'continuation',
    fixture:{stash_ref:'stash://custom &amp; space/file&amp;.pdf',filename:'Raw &amp; file.pdf'}});
const all = descendants(message(ui)), links = all.filter(el => el.tag === 'a');
assert.ok(visible(message(ui)).includes('Tom & Jerry © A *literal*'));
assert.ok(visible(message(ui)).includes('<img src=x onerror=alert(1)>'));
assert.ok(!all.some(el => el.tag === 'img'));
assert.equal(links.length, 2);
assert.equal(links[0].href, 'https://example.com/?a=1&b=2');
assert.equal(new URL(links[0].href).searchParams.get('b'), '2');
assert.equal(links[1].href, '/stash/view/custom%20%26amp%3B%20space/file%26amp%3B.pdf');
assert.equal(links[1].textContent, 'Raw &amp; file.pdf');
assert.ok(all.filter(el => el.tag === 'code').every(el => el.textContent === '&amp;'));
""")


@pytest.mark.parametrize('secure', [True, False])
def test_late_copy_is_response_only_and_preserves_existing_foreground_rail(secure):
    run_message_browser(DOM + f"\nsandbox.window.isSecureContext={json.dumps(secure)};\n" + r"""
const ui = chat(), copies = [];
const foreground = new Element(), rail = new Element();
rail.className = 'message-response-actions';
const copy = new Element(), up = new Element();
copy.addEventListener('click', () => copies.push('original question and answer'));
up.addEventListener('click', () => copies.push('reaction for original message'));
rail.appendChild(copy); rail.appendChild(up); foreground.appendChild(rail);
ui.messagesContainer.appendChild(foreground);
ui._clearMessageResponseActions = ChatUI.prototype._clearMessageResponseActions;
sandbox.navigator = {clipboard:{writeText: async text => copies.push(text)}};
Utils.copyTextFallback = text => copies.push(text); Utils.toast = () => {};
ui.pendingTools = {get_time:{status:'running'}};
ui.currentMessageId = 'current'; ui.isProcessing = true;
const before = JSON.stringify(ui.pendingTools);
ui.addAssistantMessage('Earlier job finished.', [], {_kind:'continuation'});
assert.equal(foreground.children[0], rail);
assert.equal(ui.messagesContainer.querySelectorAll('.message-response-actions').length, 2);
await descendants(message(ui)).find(el => el.tag === 'button').events.click();
copy.events.click(); up.events.click();
assert.deepEqual(copies, ['Earlier job finished.', 'original question and answer', 'reaction for original message']);
assert.equal(JSON.stringify(ui.pendingTools), before);
assert.equal(ui.currentMessageId, 'current'); assert.equal(ui.isProcessing, true);
// A subsequent ordinary response can still retire the old rails.
ui._clearMessageResponseActions();
assert.equal(ui.messagesContainer.querySelectorAll('.message-response-actions').length, 0);
""")


@pytest.mark.parametrize('form', ['live', 'saved', 'nested', 'object', 'object_nested', 'object_marker'])
@pytest.mark.parametrize('tool,filename,mime,tag', [
    ('generate_image', 'image.png', 'image/png', 'img'),
    ('generate_video', 'video.mp4', 'video/mp4', 'video'),
    ('generate_music', 'music.wav', 'audio/wav', 'audio'),
    ('create_social_clip', 'social.mp4', 'video/mp4', 'video'),
    ('convert_file', 'converted.jpg', '', 'img'),
])
def test_completed_media_uses_local_controls_without_consuming_the_live_turn(form, tool, filename, mime, tag):
    args = json.dumps({'form': form, 'tool': tool, 'filename': filename, 'mime': mime, 'tag': tag})
    run_message_browser(DOM + '\nconst args=' + args + ';\n' + r"""
const ui=chat();
ui.pendingTools={get_time:{status:'running'}}; ui.currentMessageId='foreground'; ui.isProcessing=true;
const body={filename:args.filename,mime_type:args.mime,title:'<img onerror=alert(1)>',
  provider:'<script>provider</script>',model:'reviewed-model',
  saved:{stash_ref:'stash://space_media/f_output',filename:args.filename},
  video_url:'https://provider.invalid/private-output',file_path:'/tmp/output.mp4'};
const payload={_background_mode:'cloud',[args.tool]:{ok:true,data:body}};
const before=JSON.stringify(payload);
const data=lateData(payload,args.form);
if (args.form.startsWith('object')) ui.addAssistantMessage({...data,content:'Finished'});
else ui.addAssistantMessage('Finished',[],data,args.form==='live'?{late:true}:{});
const all=descendants(message(ui)), media=all.filter(el=>el.tag===args.tag);
assert.equal(media.length,1);
assert.equal(media[0].src,'/api/stash/space_media/f_output?mode=cloud');
assert.ok(!all.some(el=>['script','svg','iframe','object'].includes(el.tag)));
assert.ok(!all.some(el=>el.src?.startsWith('http')));
const links=all.filter(el=>el.tag==='a');
assert.equal(links.length,2); // Open and Download; no duplicate artifact list.
assert.ok(links.every(el=>el.href===media[0].src));
assert.equal(links.find(el=>el.download).download,args.filename);
if(args.tag==='img') {
  const opened=[]; sandbox.window.showImageLightbox=url=>opened.push(url);
  media[0].parentElement.events.click();
  assert.deepEqual(opened,[media[0].src]);
} else {
  assert.equal(media[0].controls,true); assert.equal(media[0].autoplay,false);
  assert.equal(media[0].preload,'metadata');
  if(args.tag==='video') assert.equal(media[0].playsInline,true);
}
assert.equal(JSON.stringify(payload),before);
assert.equal(ui.currentMessageId,'foreground'); assert.equal(ui.isProcessing,true);
assert.equal(ui.pendingTools.get_time.status,'running');
assert.ok(!effects.some(e=>e==='clear-actions'||e==='hydrate'||Array.isArray(e)));
media[0].events.error();
assert.equal(media[0].hidden,true);
assert.ok(all.some(el=>el.textContent.startsWith('Preview unavailable')&&el.hidden===false));
""")


def test_media_ignores_failures_receipts_remote_urls_and_unrecognized_formats():
    run_message_browser(DOM + r"""
const ui=chat();
const body={filename:'image.png',mime_type:'image/png',saved:{stash_ref:'stash://space/f_image'}};
ui.addAssistantMessage('![remote](https://provider.invalid/image.png)',[],{_kind:'continuation',
  failed:{ok:false,data:body},receipt:{ok:true,status:'accepted',job_id:'pending',data:body},
  cancelled:{ok:true,cancelled:true,data:body},unknown:{data:body},
  remote:{ok:true,data:{filename:'image.png',file_url:'https://provider.invalid/image.png'}},
  invalid:{ok:true,data:{...body,stash_ref:'stash://space/f/extra',saved:{}}},
  html:{ok:true,data:{...body,mime_type:'text/html'}},
  prototype:{ok:true,data:{...body,mime_type:'__proto__'}},
  extension:{ok:true,data:{...body,mime_type:'',filename:'file.constructor'}}});
assert.ok(!descendants(message(ui)).some(el=>['img','video','audio'].includes(el.tag)));
""")


def test_media_deduplicates_and_keeps_unknown_files_as_links_with_literal_metadata():
    run_message_browser(DOM + r"""
const ui=chat();
const ref='stash://custom space/photo.png" onerror="alert(1)';
const body={filename:'<svg onload=alert(1)>.png',saved:{stash_ref:ref}};
ui.addAssistantMessage('Finished',[],{_kind:'continuation',_background_mode:'local',
  first:{ok:true,data:body},second:{ok:true,data:body},
  document:{ok:true,data:{filename:'report.pdf',stash_ref:'stash://space/f_report'}}});
const all=descendants(message(ui));
const images=all.filter(el=>el.tag==='img');
assert.equal(images.length,1);
assert.equal(images[0].src,'/api/stash/custom%20space/photo.png%22%20onerror%3D%22alert(1)?mode=local');
assert.ok(all.some(el=>el.tag==='a'&&el.href==='/stash/view/space/f_report?mode=local'));
assert.ok(!all.some(el=>el.tag==='svg'));
""")


@pytest.mark.parametrize('mode', ['cloud', 'local'])
def test_late_markdown_and_fallback_artifact_links_keep_original_mode(mode):
    run_message_browser(DOM + '\nconst mode=' + json.dumps(mode) + ';\n' + r"""
const ui=chat();
ui.addAssistantMessage('Read [the report](stash://space/f_report).',[],{
  _kind:'continuation',_background_mode:mode,
  convert_file:{ok:true,data:{filename:'second.pdf',stash_ref:'stash://space/f_second'}}});
const links=descendants(message(ui)).filter(el=>el.tag==='a');
assert.ok(links.some(el=>el.href==='/stash/view/space/f_report?mode='+mode));
assert.ok(links.some(el=>el.href==='/stash/view/space/f_second?mode='+mode));
""")


def test_history_recovers_original_mode_from_receipt_for_existing_continuations():
    run_message_browser(DOM + r"""
const ui=chat();
const app=Object.create(JarvisApp.prototype);
Object.assign(app,{chat:ui,socket:{mode:'local',conversationId:'thread'},
  _displayedConversationId:'thread',_completedResponseIds:new Set(),
  _updateActiveConversation(){},_updateConvIdBadge(){},_loadConversationHistory(){}});
Object.assign(ui,{setConversationLoading(){},restoreRunState(){},reconcileLiveActions(){},
  clearChat(){this.messagesContainer.children=[];this._renderedMessageIds=new Set();}});
const messages=[
  {role:'assistant',id:'receipt',content:'Queued',data:{_web_message_id:'receipt',
    _kind:'continuation',background_jobs:{job:{job_id:'job',mode:'cloud'}}}},
  {role:'assistant',id:'done',content:'Done',data:{_web_message_id:'done',_kind:'continuation',
    parent_job_id:'job',create_social_clip:{ok:true,data:{mime_type:'video/mp4',
      saved:{stash_ref:'stash://space/f_clip',filename:'clip.mp4'}}}}}
];
await app._displayLoadedConversation({id:'thread',generation:0,messages});
assert.equal(descendants(message(ui)).find(el=>el.tag==='video').src,
  '/api/stash/space/f_clip?mode=cloud');
assert.equal(messages[1].data._background_mode,undefined); // No mutation/migration.
""")
