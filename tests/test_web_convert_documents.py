"""Document conversions use the existing composer and literal artifact delivery."""
from __future__ import annotations

import re
from pathlib import Path

from test_web_assistant_message_rendering import run_message_browser

ROOT = Path(__file__).resolve().parents[1]


def test_conversion_picker_exposes_supported_documents_and_pdf_target():
    html = (ROOT / 'jarvis-web' / 'client' / 'index.html').read_text()
    picker = re.search(r'<input[^>]*id="convertInput"[^>]*>', html)
    assert picker is not None
    for extension in ('.md', '.markdown', '.txt'):
        assert extension in picker.group()
    assert 'value="pdf"' in html


def test_markdown_and_text_preselect_pdf_then_media_keep_their_existing_defaults():
    run_message_browser(r"""
const ui = chat(), fields = {};
sandbox.document.getElementById = id => fields[id] || null;
Object.assign(ui, {
  convertModal:new Element(), convertFileName:new Element(), convertPreview:new Element(),
  convertTargetFormat:{value:'png'}, convertPreviewUrl:null
});
for (const name of ['notes.md', 'notes.MARKDOWN', 'notes.txt']) {
  await ui._showConvertModal({name, type:'', size:2048});
  assert.equal(ui.convertTargetFormat.value,'pdf');
  assert.equal(ui.convertFileName.textContent,name+' (2KB)');
  assert.match(ui.convertPreview.innerHTML,/📄/);
}
for (const [name, type, expected] of [
  ['image.png','image/png','webp'], ['photo.jpg','image/jpeg','png'],
  ['clip.mp4','video/mp4','webm'], ['clip.mov','video/quicktime','mp4'],
  ['music.mp3','audio/mpeg','wav'], ['sound.wav','audio/wav','mp3']
]) {
  ui._preselectFormat('notes.md','document');
  ui._preselectFormat(name,type.split('/')[0]);
  assert.equal(ui.convertTargetFormat.value,expected);
}
""")


def test_pdf_format_hides_media_options_and_never_sends_stale_background_removal():
    run_message_browser(r"""
const ui=chat(), fields={};
for (const id of ['convertImageOptions','convertSvgOptions','convertVideoOptions','convertAudioOptions',
  'convertBackgroundOptions','convertRemoveBackground','convertBackgroundColor','convertBackgroundTolerance',
  'convertResize','convertQuality','convertStripMetadata','convertGrayscale','convertFormatDesc']) {
  fields[id]={style:{}, value:'', checked:false};
}
sandbox.document.getElementById=id=>fields[id]||null;
ui.convertTargetFormat={value:'png'};
fields.convertRemoveBackground.checked=true;
fields.convertResize.value='800x600';
fields.convertQuality.value='90';
fields.convertStripMetadata.checked=true;
ui.convertTargetFormat.value='pdf';
ui._updateConvertOptions();
ui._updateFormatDescription();
for (const id of ['convertImageOptions','convertSvgOptions','convertVideoOptions','convertAudioOptions'])
  assert.equal(fields[id].style.display,'none');
assert.equal(fields.convertBackgroundOptions.hidden,true);
assert.deepEqual(JSON.parse(JSON.stringify(ui._collectConvertOptions())),{});
assert.match(fields.convertFormatDesc.textContent,/PDF.*Markdown.*text/);
ui.convertTargetFormat.value='png';
ui._updateConvertOptions();
assert.equal(fields.convertBackgroundOptions.hidden,false);
assert.equal(ui._collectConvertOptions().remove_background,true);
""")


def test_document_conversion_uploads_original_and_submits_exact_pdf_action():
    run_message_browser(r"""
const ui=chat(), requests=[], calls=[];
sandbox.FormData=class {constructor(){this.entries=[];} append(...args){this.entries.push(args);}};
sandbox.fetch=async(url,options)=>{requests.push({url,options});return {
  ok:true,json:async()=>({stash_ref:'stash://uploaded_markdown/f_source'})};};
Utils.toast=()=>{};
Object.assign(ui, {
  pendingConvertFile:{file:{name:'notes.md',type:'text/markdown',size:99}},
  convertTargetFormat:{value:'pdf'},inputField:{value:''},
  _hideConvertModal(){this.pendingConvertFile=null;},
  sendMessage:async action=>calls.push(action)
});
sandbox.document.getElementById=()=>null;
await ui._executeConversion();
assert.equal(requests.length,1);
assert.equal(requests[0].url,'/api/stash/upload');
assert.equal(requests[0].options.body.entries[0][1].name,'notes.md');
assert.deepEqual(JSON.parse(JSON.stringify(calls)),[{tool:'convert_file',arguments:{
  source:'stash://uploaded_markdown/f_source',target_format:'pdf',options:{}}}]);
assert.match(ui.inputField.value,/to PDF format.*Use the convert_file tool/);
""")


def test_reused_conversion_picker_resets_pdf_only_choices_for_empty_mime_media():
    run_message_browser(r"""
const ui=chat();
sandbox.document.getElementById=()=>null;
sandbox.URL={createObjectURL:()=> 'blob:test-convert',revokeObjectURL(){}};
Object.assign(ui, {
  convertModal:new Element(),convertFileName:new Element(),convertPreview:new Element(),
  convertTargetFormat:{value:'png',options:['png','jpg','webp','mp4','webm','mp3','wav','pdf'].map(value=>({value,disabled:false}))},
  convertPreviewUrl:null
});
for (const [name, expected] of [['photo.png','webp'],['music.mp3','wav'],['clip.mp4','webm']]) {
  await ui._showConvertModal({name:'notes.md',type:'',size:100});
  assert.equal(ui.convertTargetFormat.value,'pdf');
  assert.ok(ui.convertTargetFormat.options.every(option=>option.disabled===(option.value!=='pdf')));
  await ui._showConvertModal({name,type:'',size:100});
  assert.equal(ui.convertTargetFormat.value,expected);
  assert.ok(ui.convertTargetFormat.options.every(option=>option.disabled===(option.value==='pdf')));
}
// Even an unknown source cannot retain the disabled PDF selection from a document.
await ui._showConvertModal({name:'notes.txt',type:'text/plain',size:100});
await ui._showConvertModal({name:'unknown.bin',type:'',size:100});
assert.equal(ui.convertTargetFormat.value,'png');
assert.equal(ui.convertTargetFormat.options.find(option=>option.value==='pdf').disabled,true);
""")


def test_document_limit_is_five_mib_before_any_upload_and_accepts_exact_limit():
    run_message_browser(r"""
const ui=chat(), notices=[], requests=[];
sandbox.document.getElementById=()=>null;
sandbox.fetch=async(...args)=>{requests.push(args);throw new Error('Oversized document uploaded');};
Utils.toast=(...args)=>notices.push(args);
Object.assign(ui, {
  convertModal:new Element(),convertFileName:new Element(),convertPreview:new Element(),
  convertTargetFormat:{value:'png',options:[{value:'png'},{value:'pdf'}]},convertPreviewUrl:null,
  pendingConvertFile:null
});
for (const name of ['notes.md','notes.MARKDOWN','notes.txt']) {
  await ui._showConvertModal({name,type:'',size:5*1024*1024+1});
  assert.equal(ui.pendingConvertFile,null);
  assert.equal(ui.convertModal.classList.contains('active'),false);
}
assert.equal(requests.length,0);
assert.equal(notices.length,3);
assert.ok(notices.every(([text,kind])=>text.includes('5 MiB') && kind==='error'));
await ui._showConvertModal({name:'notes.md',type:'text/markdown',size:5*1024*1024});
assert.equal(ui.pendingConvertFile.file.size,5*1024*1024);
assert.equal(ui.convertTargetFormat.value,'pdf');
assert.equal(ui.convertModal.classList.contains('active'),true);
""")
