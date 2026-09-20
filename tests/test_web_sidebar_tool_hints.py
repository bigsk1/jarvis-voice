"""Sidebar tool selection shares the composer hint behavior on desktop and mobile."""

from test_web_attachment_bundle_ui import run_browser


def test_sidebar_tool_rows_add_composer_hints_and_keep_unusable_tools_informational():
    run_browser(r"""
sandbox.Utils.truncate=(value, limit)=>String(value).slice(0, limit);
const ui=chat();
ui.toolHintsContainer=new Element();
ui._renderToolHintChips=ChatUI.prototype._renderToolHintChips;
ui._updateAmbientToolSuggestions=()=>{};
let focused=0;
ui.inputField.focus=()=>{focused++;};
const app=Object.create(JarvisApp.prototype);
app.chat=ui;
app.modeSelect={value:'cloud'};
app.socket={mode:'cloud'};
const tools=new Map([
  ['generate_image',{name:'generate_image',available:true}],
  ['recall',{name:'recall',available:true}]
]);
let refreshed=0;
sandbox.window.commandSystem={
  maxToolHints:5,
  getTool:name=>tools.get(name)||null,
  refreshTools:async()=>{refreshed++;tools.set('weather',{name:'weather',available:true});}
};
let mobile=true;
sandbox.window.matchMedia=()=>({matches:mobile});
const removed=[];
const sidebar={classList:{remove:name=>removed.push(name)}};
sandbox.document.getElementById=id=>id==='sidebar'?sidebar:null;
sandbox.document.body={classList:{remove:name=>removed.push(name)}};
const click=name=>app._onToolItemClick({target:{closest:()=>({dataset:{toolName:name}})}});

const ready=app._renderToolItem({name:'generate_image',description:'Create an image',source:'local'});
assert.match(ready,/<button class="tool-item" type="button" data-tool-name="generate_image"/);
assert.match(ready,/class="tool-item-add"/);
assert.match(ready,/Create an image/);
assert.match(app._renderToolItem({name:'send_email',blocked:true,description:'Send mail'}),
  /<div class="tool-item tool-blocked"/);
assert.match(app._renderToolItem({name:'weather',available:false,description:'Forecast'}),
  /<div class="tool-item tool-unavailable"/);

await click('generate_image');
assert.deepEqual(ui.selectedToolHints,['generate_image']);
assert.match(ui.toolHintsContainer.innerHTML,/#generate_image/);
assert.equal(ui.inputField.value,'Compare these sources','the current draft must stay intact');
assert.equal(focused,1);
assert.deepEqual(removed,['mobile-open','sidebar-open']);
await click('generate_image');
assert.deepEqual(ui.selectedToolHints,['generate_image'],'a second tap must not duplicate the hint');

mobile=false;
await click('recall');
assert.deepEqual(ui.selectedToolHints,['generate_image','recall']);
assert.equal(removed.length,4,'desktop selection must leave the sidebar open');
assert.equal(focused,3);

await click('weather');
assert.equal(refreshed,1,'a newly loaded sidebar row can recover a stale hint registry');
assert.deepEqual(ui.selectedToolHints,['generate_image','recall','weather']);

ui.chatOnlyEnabled=true;
await click('generate_image');
assert.deepEqual(ui.selectedToolHints,['generate_image','recall','weather'],
  'Chat only must still reject sidebar selections');

ui.chatOnlyEnabled=false;
ui.selectedToolHints=['generate_image','recall','weather','send_email','search_memory'];
tools.set('send_webhook',{name:'send_webhook',available:true});
const focusBeforeLimit=focused;
await click('send_webhook');
assert.equal(ui.selectedToolHints.length,5,'sidebar selection must keep the composer hint cap');
assert.equal(focused,focusBeforeLimit);
""")
