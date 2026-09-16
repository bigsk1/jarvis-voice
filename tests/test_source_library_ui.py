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
  querySelector(selector) { return flatten(this).find(child=>selector==='[data-next]' && child.dataset.next) || null; }
  remove() { if(this.parent) this.parent.children=this.parent.children.filter(child=>child!==this); }
  scrollIntoView() {}
  focus() { this.focused=true; }
  reset() { elements.file.files=[]; elements.title.value=''; }
  click() { return this.listeners.click?.({preventDefault(){}}); }
}
function flatten(element) { return element.children.flatMap(child=>[child,...flatten(child)]); }
const elements=Object.fromEntries(['mode','file','title','save','upload-form','query','search-form','semantic','browse','status','stop-index','results','more','detail'].map(id=>[id,new Element()]));
const document={getElementById:id=>elements[id],createElement:tag=>new Element(tag),body:new Element('body')};
document.querySelectorAll=()=>Object.values(elements).flatMap(element=>flatten(element)).filter(element=>element.dataset.libraryIndex);
const sid='a'.repeat(64);
const source={source_id:sid,mode:'local',title:'<img src=x onerror=alert(1)>',filename:'note.txt',passage_count:20,indexed_passages:0,empty_pages:[],index_status:'keyword_only'};
const passage={...source,number:3,text:'Deep passage evidence <script>malicious()</script>',citation:'Note, page 2, lines 9–10',page:2};
const calls=[];
let pendingSearch=null, pendingIndex=null, pendingRead=null, delaySearch=false, delayIndex=false, delayRead=false, indexCalls=0;
function answer(data) { return {ok:true,status:200,json:async()=>({ok:true,...data})}; }
async function fetcher(raw, options={}) {
  const url=new URL(raw,'http://jarvis.test:5001'); calls.push([url,options]);
  if(url.pathname.endsWith('/index')) {
    indexCalls++;
    if(delayIndex) return new Promise(resolve=>{pendingIndex=resolve;});
    return answer({source:{...source,indexed_passages:20},remaining:0});
  }
  if(options.method==='DELETE') return answer({removed:true});
  if(options.method==='POST') return answer({source:{...source,mode:url.searchParams.get('mode')}});
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
const window={location:{search:'?mode=local&source='+sid+'&passage=3',origin:'http://jarvis.test:5001'},history:{replaceState(_state,_title,url){history.push(url);}},confirm:()=>false,setTimeout,addEventListener(){}};
const sandbox={window,document,URL,URLSearchParams,console,FormData:class{append(){}},Utils:{auth:{fetch:fetcher}}};
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
  assert.ok(elements.status.textContent.includes('1 saved sources'));
  elements.query.value='deep evidence';
  await elements['search-form'].listeners.submit({preventDefault(){}});
  assert.ok(elements.results.textContent.includes(passage.text));
  assert.deepEqual(highlights(elements.results),['Deep','evidence']);
  await elements.results.children[0].children[0].click(); await tick();
  assert.equal(elements.detail.hidden,false);
  assert.ok(elements.detail.textContent.includes(passage.text));
  assert.deepEqual(highlights(elements.detail),['Deep','evidence']);
  await findButton(elements.detail,'Close source').click();
  assert.equal(elements.detail.hidden,true);
  assert.equal(history.at(-1),'/library?mode=local');
  assert.equal(elements.query.focused,true);
  await findButton(elements.results,'View full passage').click();
  assert.equal(elements.detail.hidden,false);
  const removes=()=>calls.filter(([_,o])=>o.method==='DELETE').length;
  await findButton(elements.detail,'Remove').click();
  assert.equal(removes(),0,'Dismissed removal must not call the API');
  delayIndex=true;
  const indexing=findButton(elements.detail,'Index remaining').click();
  await tick();
  assert.equal(elements.mode.disabled,true);
  elements['stop-index'].listeners.click();
  pendingIndex(answer({source:{...source,indexed_passages:16},remaining:4}));
  await indexing;
  assert.equal(indexCalls,1,'Pause must not schedule another batch');
  assert.ok(elements.status.textContent.includes('paused'));
  assert.ok(elements.detail.textContent.includes('16 indexed by meaning'));
  assert.equal(elements.mode.disabled,false);
  delayIndex=false;
  await findButton(elements.detail,'Index remaining').click();
  assert.equal(indexCalls,2);
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
  assert.ok(elements.results.textContent.includes('No literal match'));
  passage.text='x'.repeat(301)+'🌲'.repeat(100)+'SILVER FERN'+'🪴'.repeat(300);
  elements.query.value='silver fern';
  await elements['search-form'].listeners.submit({preventDefault(){}});
  assert.deepEqual(highlights(elements.results),['SILVER FERN']);
  assert.ok(preview(elements.results).textContent.isWellFormed(),'Excerpt edges must preserve Unicode characters');
  delaySearch=true;
  const stale=elements['search-form'].listeners.submit({preventDefault(){}});
  await tick();
  elements.mode.value='cloud'; elements.mode.listeners.change(); await tick();
  pendingSearch(answer({passages:[passage],retrieval_mode:'hybrid'}));
  await stale;
  assert.equal(elements.results.children.length,0,'A local search must not paint the cloud library');
  assert.ok(elements.status.textContent.includes('cloud'));
  elements.file.files=[{size:100,name:'note.txt'}];
  await elements['upload-form'].listeners.submit({preventDefault(){}});
  assert.equal(elements.save.disabled,false);
  assert.ok(calls.some(([u,o])=>o.method==='POST'&&u.pathname==='/api/library'&&u.searchParams.get('mode')==='cloud'));
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
    subprocess.run(["node", "-e", script, str(ROOT)], check=True, timeout=15)


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
