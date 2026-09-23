"""Run the shipped classic scripts against a small deterministic browser DOM."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_library_browser_lifecycle_and_stale_request_protection():
    script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
class Element {
  constructor(tag='div') { this.tag=tag; this.children=[]; this.listeners={}; this.dataset={}; this.value=''; this.files=[]; this.checked=true; this.hidden=false; }
  set textContent(text) { this.text=String(text); this.children=[]; }
  get textContent() { return (this.text || '') + this.children.map(c=>c.textContent).join(''); }
  set innerHTML(value) { throw Error('Source content must not use innerHTML'); }
  append(...children) { for(const child of children) { child.parent=this; this.children.push(child); } }
  replaceChildren(...children) { this.text=''; this.children=[]; this.append(...children); }
  addEventListener(type, callback) { this.listeners[type]=callback; }
  setAttribute(name,value) { this[name]=value; }
  querySelector(selector) { return flatten(this).find(child=>selector==='[data-next]' && child.dataset.next) || null; }
  remove() { if(this.parent) this.parent.children=this.parent.children.filter(child=>child!==this); }
  scrollIntoView() {}
  focus() { this.focused=true; }
  reset() { elements.file.files=[]; elements.title.value=''; }
  click() { return this.listeners.click?.({preventDefault(){}}); }
}
function flatten(element) { return element.children.flatMap(child=>[child,...flatten(child)]); }
const elements=Object.fromEntries(['mode','file','title','save','clear-files','selected-files','selection-count','upload-form','import-progress','inbox-section','check-inbox','queue-inbox','inbox-status','query','search-form','semantic','browse','clear-search','search-context','status','worker-health','refresh','results','more','detail'].map(id=>[id,new Element()]));
const document={getElementById:id=>elements[id],createElement:tag=>new Element(tag),body:new Element('body')};
document.querySelectorAll=selector=>Object.values(elements).flatMap(element=>flatten(element))
  .filter(element=>selector==='[data-library-index-action]' ? element.dataset.libraryIndexAction : element.dataset.libraryIndex);
const sid='a'.repeat(64);
const source={source_id:sid,mode:'local',title:'<img src=x onerror=alert(1)>',filename:'note.md',origin:'Firefox page capture at 2026-09-23T10:00:00Z; client-reported URL: https://example.test',passage_count:20,indexed_passages:0,empty_pages:[],index_status:'keyword_only'};
const passage={...source,number:3,text:'Deep passage evidence <script>malicious()</script>',citation:'Note, page 2, lines 9–10',page:2,match_reasons:['text']};
const calls=[];
let pendingSearch=null, pendingRead=null, delaySearch=false, delayRead=false, queueCalls=0, failSecondUpload=true, workerHealthy=true;
function answer(data) { return {ok:true,status:200,json:async()=>({ok:true,...data})}; }
async function fetcher(raw, options={}) {
  const url=new URL(raw,'http://jarvis.test:5001'); calls.push([url,options]);
  if(url.pathname.endsWith('/queue')) {
    queueCalls++;
    return answer({source:{...source,index_job_status:'pending'},queued:true});
  }
  if(url.pathname.endsWith('/worker')) return answer({running:workerHealthy,worker_mode:'external'});
  if(url.pathname.endsWith('/inbox')) return answer({eligible_count:0,queueable_count:0,skipped_count:0,estimated_disk_bytes:0,free_disk_bytes:1048576,inbox_path:'/tmp/inbox',job_counts:{},jobs:[]});
  if(url.pathname.endsWith('/status')) return answer({sources:[{...source,indexed_passages:16,index_job_status:'pending'}]});
  if(url.pathname.endsWith('/text')) return answer({text:'# Original note'});
  if(url.pathname.endsWith('/rendered')) return answer({html:'<h1>Original note</h1>'});
  if(url.pathname.endsWith('/copy')) return answer({source:{...source,duplicate:true}});
  if(options.method==='DELETE') return answer({removed:true});
  if(options.method==='POST') {
    if(options.body?.values?.file?.name==='second.txt'&&failSecondUpload) {
      failSecondUpload=false;
      return {ok:false,status:400,json:async()=>({ok:false,error:'Temporary import failure'})};
    }
    return answer({source:{...source,mode:url.searchParams.get('mode')}});
  }
  if(url.searchParams.has('q')) {
    if(delaySearch) return new Promise(resolve=>{pendingSearch=resolve;});
    return answer({passages:[passage],retrieval_mode:'keyword'});
  }
  if(url.pathname.endsWith('/'+sid)) {
    if(delayRead) return new Promise(resolve=>{pendingRead=resolve;});
    return answer({source,passages:[passage],next_passage:null});
  }
  return answer({sources:url.searchParams.get('mode')==='cloud'?[]:[source],total:url.searchParams.get('mode')==='cloud'?0:1,next_offset:null});
}
const history=[];
const window={location:{search:'?mode=local&source='+sid+'&passage=3',origin:'http://jarvis.test:5001'},history:{replaceState(_state,_title,url){history.push(url);}},confirm:()=>false,prompt:()=>null,setTimeout,addEventListener(){}};
const sandbox={window,document,URL,URLSearchParams,console,FormData:class{constructor(){this.values={};}append(k,v){this.values[k]=v;}},Utils:{auth:{fetch:fetcher}}};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(process.argv[1]+'/jarvis-web/client/js/library.js','utf8'),sandbox);
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const findButton=(root,label)=>flatten(root).find(x=>x.tag==='button'&&x.textContent===label);
const highlights=root=>flatten(root).filter(x=>x.tag==='mark').map(x=>x.textContent);
const preview=root=>flatten(root).find(x=>x.tag==='pre');
(async()=>{
  await tick();
  assert.ok(history.every(url=>url.includes('source='+sid)), 'Initial loading must preserve the citation URL');
  assert.ok(elements.results.textContent.includes(source.title));
  assert.ok(elements.results.textContent.includes('Captured 2026-09-23'));
  assert.ok(elements.status.textContent.includes('1 saved sources'));
  assert.equal(elements['worker-health'].hidden,true);
  workerHealthy=false;
  elements.refresh.click(); await tick();
  assert.equal(elements['worker-health'].hidden,false,'A stopped worker must be visible near the library heading');
  assert.ok(elements['worker-health'].textContent.toLowerCase().includes('queued inbox imports'));
  workerHealthy=true;
  elements.refresh.click(); await tick();
  assert.equal(elements['worker-health'].hidden,true,'The warning clears when the worker returns');
  elements.query.value='deep evidence';
  await elements['search-form'].listeners.submit({preventDefault(){}});
  assert.ok(elements.results.textContent.includes(passage.text));
  assert.deepEqual(highlights(elements.results),['Deep','evidence']);
  assert.equal(elements.results.children.length,1,'Passages are grouped under one source');
  assert.ok(elements['search-context'].textContent.includes('deep evidence'));
  assert.equal(elements['clear-search'].hidden,false);
  passage.match_reasons=['semantic'];
  await elements['search-form'].listeners.submit({preventDefault(){}});
  assert.deepEqual(highlights(elements.results),[],'A semantic-only hit must not be painted as a literal match');
  passage.match_reasons=['text'];
  await elements['search-form'].listeners.submit({preventDefault(){}});
  await findButton(elements.results,'Search within').click();
  assert.ok(calls.at(-1)[0].searchParams.get('source')===sid);
  await findButton(elements['search-context'],'Search all sources').click();
  assert.equal(calls.at(-1)[0].searchParams.has('source'),false);
  await findButton(elements.results,'Open source').click(); await tick();
  assert.equal(elements.detail.hidden,false);
  assert.ok(elements.detail.textContent.includes(passage.text));
  assert.equal(flatten(elements.detail).filter(x=>x.className==='source-card').length,0,'Reader must not repeat the browse card');
  assert.ok(flatten(elements.detail).some(x=>x.className==='reader-title-row'&&findButton(x,'Close source')),'Close belongs beside the reader title');
  assert.equal(findButton(elements.detail,'Delete source').parent.className,'actions','Deletion must be visible in the reader');
  assert.deepEqual(highlights(elements.detail),['Deep','evidence']);
  await findButton(elements.detail,'Close source').click();
  assert.equal(elements.detail.hidden,true);
  assert.equal(history.at(-1),'/library?mode=local');
  assert.equal(elements.query.focused,true);
  await findButton(elements.results,'View full passage').click();
  assert.equal(elements.detail.hidden,false);
  const removes=()=>calls.filter(([_,o])=>o.method==='DELETE').length;
  await findButton(elements.detail,'Delete source').click();
  assert.equal(removes(),0,'Dismissed removal must not call the API');
  await findButton(elements.detail,'Queue meaning index').click();
  assert.equal(queueCalls,1,'The browser queues indexing instead of running batches itself');
  assert.ok(elements.status.textContent.includes('continues after you leave'));
  assert.notEqual(elements.mode.disabled,true);
  findButton(elements.detail,'Rendered view').click(); await tick();
  const frame=flatten(elements.detail).find(x=>x.tag==='iframe');
  assert.equal(frame.sandbox,'');
  assert.ok(frame.srcdoc.includes("default-src 'none'"));
  findButton(elements.detail,'Original / raw').click(); await tick();
  const editor=flatten(elements.detail).find(x=>x.tag==='textarea');
  assert.equal(editor.value,'# Original note');
  editor.value='# Edited note';
  findButton(elements.detail,'Save edited copy').click(); await tick(); await tick();
  assert.ok(calls.some(([u,o])=>u.pathname.endsWith('/copy')&&o.method==='POST'));
  // Literal punctuation and raw HTML/remote image syntax must remain text.
  passage.text='Unrelated background. '.repeat(50)+'Exact [flag]+? <img src="https://example.test/pixel"> ![remote](https://example.test/image.png) '+'Later context. '.repeat(40);
  elements.query.value='[flag]+?';
  await elements['search-form'].listeners.submit({preventDefault(){}});
  assert.deepEqual(highlights(elements.results),['[flag]+?']);
  assert.ok(preview(elements.results).textContent.startsWith('… '));
  assert.ok(preview(elements.results).textContent.length<500);
  assert.ok(preview(elements.results).textContent.includes('<img src="https://example.test/pixel">'));
  assert.ok(!flatten(elements.results).some(x=>['img','iframe','script'].includes(x.tag)));
  await findButton(elements.results,'View full passage').click();
  assert.equal(preview(elements.detail).textContent,passage.text,'Expanded view keeps all raw passage characters');
  assert.deepEqual(highlights(elements.detail),['[flag]+?']);
  delayRead=true;
  const lateRead=findButton(elements.results,'View full passage').click();
  await tick();
  await findButton(elements.detail,'Close source').click();
  pendingRead(answer({source,passages:[passage],next_passage:null}));
  await lateRead;
  assert.equal(elements.detail.hidden,true,'A late read must not reopen a closed source');
  assert.equal(elements.detail.children.length,0);
  delayRead=false;
  elements.query.value='orbital rendezvous';
  await elements['search-form'].listeners.submit({preventDefault(){}});
  assert.deepEqual(highlights(elements.results),[]);
  assert.ok(elements.results.textContent.includes('Keyword retrieval found this passage'));
  passage.text='x'.repeat(301)+'🌲'.repeat(100)+'SILVER FERN'+'🪴'.repeat(300);
  elements.query.value='silver fern';
  await elements['search-form'].listeners.submit({preventDefault(){}});
  assert.deepEqual(highlights(elements.results),['SILVER FERN']);
  assert.ok(preview(elements.results).textContent.isWellFormed(),'Excerpt edges must preserve Unicode characters');
  elements.query.value='';
  elements.query.listeners.input();
  await tick();
  assert.equal(elements['search-context'].hidden,true,'Clearing input resets active results');
  assert.ok(elements.results.textContent.includes(source.title));
  elements.query.value='silver fern';
  await elements['search-form'].listeners.submit({preventDefault(){}});
  delaySearch=true;
  const stale=elements['search-form'].listeners.submit({preventDefault(){}});
  await tick();
  elements.mode.value='cloud'; elements.mode.listeners.change(); await tick();
  pendingSearch(answer({passages:[passage],retrieval_mode:'hybrid'}));
  await stale;
  assert.ok(!elements.results.textContent.includes(source.title),'A local search must not paint the cloud library');
  assert.ok(elements.status.textContent.includes('cloud'));
  const posts=()=>calls.filter(([u,o])=>o.method==='POST'&&u.pathname==='/api/library'&&u.searchParams.get('mode')==='cloud').length;
  elements.file.files=[{size:100,name:'wrong.txt',lastModified:1},{size:100,name:'note.txt',lastModified:2},{size:100,name:'second.txt',lastModified:3}];
  elements.file.listeners.change();
  assert.equal(posts(),0,'Picking files must not upload them');
  assert.equal(elements.save.disabled,false);
  assert.ok(elements['selected-files'].textContent.includes('wrong.txt'));
  await findButton(elements['selected-files'],'Remove from list').click();
  assert.ok(!elements['selected-files'].textContent.includes('wrong.txt'));
  assert.equal(elements['selected-files'].textContent.includes('2 files ready to add'),true);
  assert.equal(elements['selection-count'].textContent,'2 chosen · cloud','Collapsed import panel must show pending files and destination');
  await elements['upload-form'].listeners.submit({preventDefault(){}});
  assert.equal(elements.save.disabled,true,'Import is disabled until another file is selected');
  assert.equal(elements['selected-files'].hidden,true);
  assert.equal(elements['selection-count'].hidden,true);
  assert.equal(posts(),2);
  assert.ok(elements['import-progress'].textContent.includes('2 sources'));
  assert.ok(elements['import-progress'].textContent.includes('Temporary import failure'));
  findButton(elements['import-progress'],'Retry this file').click(); await tick(); await tick();
  assert.equal(posts(),3);
  assert.ok(!elements['import-progress'].textContent.includes('Temporary import failure'));
  elements.file.files=[{size:100,name:'unsaved.txt',lastModified:4}];
  elements.file.listeners.change();
  assert.equal(elements.title.disabled,false,'One selected file may have a custom title');
  elements['clear-files'].click();
  assert.equal(elements['selected-files'].hidden,true);
  assert.equal(elements.save.disabled,true);
  assert.equal(posts(),3,'Clear list must not write to the library');
  elements.file.files=[{size:100,name:'local-only.txt',lastModified:5}];
  elements.file.listeners.change();
  elements.mode.value='local'; elements.mode.listeners.change(); await tick();
  assert.equal(elements['selected-files'].hidden,true,'Switching libraries clears the unsaved selection');
  assert.equal(posts(),3);
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
    subprocess.run(["node", "-e", script, str(ROOT)], check=True, timeout=15)


def test_import_picker_uses_reviewable_selection_not_native_required_file_input():
    html = (ROOT / "jarvis-web/client/library.html").read_text()
    assert "Choose files" in html and "Add to library" in html
    assert "Choosing files only puts them on this list" in html
    assert "index their text in the library database for retrieval" in html
    assert "does not copy files into the server inbox" in html
    assert "Add files to selection" not in html
    file_input = html.split('id="file"', 1)[1].split(">", 1)[0]
    assert "multiple" in file_input
    assert "required" not in file_input
    assert 'id="selected-files"' in html
    assert 'id="selection-count"' in html
    assert 'id="clear-files"' in html
    assert 'id="worker-health"' in html
    assert 'role="alert"' in html


def test_saved_chat_card_escapes_text_and_constructs_only_local_source_links():
    from test_structured_results_adapters import _run_renderer_assertions

    _run_renderer_assertions(r"""
sandbox.location={origin:'https://jarvis.example.test'};
const sid='a'.repeat(64);
const payload={mode:'local',retrieval_mode:'keyword',passages:[{
  source_id:sid,mode:'local',number:7,title:'<img src=x onerror=alert(1)>',
  text:'Evidence <script>alert(1)</script>',url:'javascript:alert(1)',
}]};
const html=renderer.render({source_library:payload});
assert.ok(html.includes('source='+sid));
assert.ok(html.includes('passage=7'));
assert.ok(html.includes('https://jarvis.example.test/library'));
assert.ok(html.includes('&lt;script&gt;'));
assert.ok(!html.includes('href="javascript:'));
assert.ok(!html.includes('<img src=x'));
assert.equal(html,renderer.render({source_library:{data:payload}}));
assert.equal(renderer.render({source_library:{passages:[{...payload.passages[0],source_id:'bad'}]}}),'');
""")


def test_expired_auth_and_both_login_paths_keep_source_citations():
    script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const root=process.argv[1], destination='/library?mode=local&source='+'a'.repeat(64)+'&passage=7';
const element=()=>({value:'test-password',classList:{add(){},remove(){}},addEventListener(){},focus(){}});
const document={addEventListener(){},getElementById:()=>element()};
const window={location:{pathname:'/library',search:destination.slice(8),hash:'',origin:'http://jarvis.test:5001'}};
const localStorage={getItem:()=>null,removeItem(){},setItem(){}};
const sandbox={window,document,localStorage,URL,URLSearchParams,console,fetch:async()=>({status:401})};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(root+'/jarvis-web/client/js/utils.js','utf8'),sandbox);
const login=fs.readFileSync(root+'/jarvis-web/client/login.html','utf8').match(/<script>\s*([\s\S]*?)<\/script>/)[1];
(async()=>{
  await assert.rejects(window.Utils.auth.fetch('/api/library'),/Authentication required/);
  assert.equal(new URL(window.location.href,window.location.origin).searchParams.get('redirect'),destination);
  for(const existingToken of [null,'existing-token']) {
    const location={origin:'http://jarvis.test:5001',search:'?redirect='+encodeURIComponent(destination)};
    const context={window:{location},document,URL,URLSearchParams,Math,Date,
      localStorage:{...localStorage,getItem:()=>existingToken},
      fetch:async()=>({json:async()=>({ok:true,token:'test-token'})})};
    vm.createContext(context); vm.runInContext(login,context);
    if(!existingToken) await vm.runInContext('doLogin()',context);
    await new Promise(resolve=>setImmediate(resolve));
    assert.equal(location.href,destination,'Both sign-in and cookie restoration must retain the citation');
  }
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
    subprocess.run(["node", "-e", script, str(ROOT)], check=True, timeout=15)
