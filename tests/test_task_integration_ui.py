"""Execute the shipped integration controls with inert browser I/O."""
from test_web_attachment_bundle_ui import run_browser

SETUP = r"""
Element.prototype.prepend=function(item){this.children.unshift(item);};
Element.prototype.scrollIntoView=function(){};
const root=new Element(), close=new Element(), modal=new Element();
const elements={taskIntegrations:root,closeSettings:close,settingsModal:modal};
sandbox.document.getElementById=id=>elements[id]||null;
sandbox.document.querySelector=()=>null;
sandbox.document.addEventListener=(event,fn)=>{sandbox.document[event]=fn;};
sandbox.window.confirm=()=>true;
const state={enabled:false,key_ready:true,sources:[]};
const calls=[];
sandbox.Utils.auth={fetch:async(url,options)=>{
  calls.push({url,...options});
  return {ok:true,json:async()=>url.endsWith('/credentials')?{id:'key',secret:'once-only',scheme:'bearer',authorization:'Bearer key.once-only'}:state};
}};
const Controls=loadClass(ROOT+'/jarvis-web/client/js/webhook-integrations.js','WebhookIntegrations','window.WebhookIntegrations');
const controls=new Controls({});
"""


def test_operator_toggle_uses_web_origin_and_reports_failed_save():
    run_browser(SETUP + r"""
await controls.refresh();
const toggle=controls.content.children[0].children[0];
toggle.checked=true;
await toggle.change();
assert.equal(calls[1].url,'/api/task-integrations');
assert.equal(calls[1].method,'PATCH');
assert.equal(JSON.parse(calls[1].body).enabled,true);
sandbox.Utils.auth.fetch=async()=>({ok:false,json:async()=>({error:'Web origin is not allowed'})});
toggle.checked=true;
await toggle.change();
assert.equal(toggle.checked,false);
assert.equal(toggle.disabled,false);
assert.match(controls.notice.textContent,/Web origin/);
""")


def test_one_time_credential_is_cleared_on_close_escape_and_backdrop():
    run_browser(SETUP + r"""
for(const dismiss of [()=>close.click(),()=>sandbox.document.keydown({key:'Escape'}),()=>modal.click({target:{id:'settingsModal'}})]) {
 await controls.createCredential({id:'source'},{scheme:'bearer'});
 assert.equal(controls.secret.hidden,false);
 assert.equal(controls.secret.children.find(item=>item.tag==='textarea').value,'Bearer key.once-only');
 assert.equal(JSON.stringify(state).includes('once-only'),false);
 dismiss();
 assert.equal(controls.secret.hidden,true);
 assert.equal(controls.secret.children.length,0);
}
assert(calls.every(item=>item.url.startsWith('/api/task-integrations')));
""")


def test_source_and_delivery_content_remain_text_and_disposition_is_explicit():
    run_browser(SETUP + r"""
const unsafe='<img src=x onerror=alert(1)>';
const source={id:'source',name:unsafe,endpoint:'https://example.test/events',events:[],credentials:[],revoked:true,outstanding:0};
const card=controls.sourceCard(source,true);
assert.equal(card.children[0].textContent,unsafe);
assert.equal(card.children[0].innerHTML,'');
const output=new Element();
sandbox.Utils.auth.fetch=async()=>({ok:true,json:async()=>({deliveries:[{event_id:'evt',job_id:'job-42',attempt_id:'attempt-17',credential_id:'cred-3',payload_digest:'digest-4',event_type:'task.completed',state:'held',reason:unsafe,verified_at:1,attempts:1}],total:1})});
await controls.loadDeliveries(source,output,0);
assert.match(output.children[0].children[1].textContent,/<img/);
assert.equal(output.children[0].children[1].innerHTML,'');
assert.equal(output.children[0].children[2].textContent,'Event: evt · Job: job-42');
const verification=output.children[0].children[3];
assert.equal(verification.children[1].textContent,'Attempt: attempt-17');
assert.equal(verification.children[2].textContent,'Credential: cred-3');
assert.equal(verification.children[3].textContent,'Payload digest: digest-4');
const discard=output.children[0].children[4];
assert.equal(discard.textContent,'Discard held event');
let confirmation='';
sandbox.window.confirm=text=>{confirmation=text;return false;};
await discard.click();
assert.match(confirmation,/event evt for job job-42/);
""")


def test_closing_settings_during_credential_creation_does_not_redisplay_secret():
    run_browser(SETUP + r"""
const pending=deferred();
const original=sandbox.Utils.auth.fetch;
sandbox.Utils.auth.fetch=(url,options)=>url.endsWith('/credentials')?pending.promise:original(url,options);
const creating=controls.createCredential({id:'source'},{scheme:'bearer'});
close.click();
pending.resolve({ok:true,json:async()=>({authorization:'Bearer should-not-reappear'})});
await creating;
assert.equal(controls.secret.hidden,true);
assert.equal(controls.secret.children.length,0);
""")


def test_managed_browser_source_keeps_normal_setup_out_of_advanced_integrations():
    run_browser(SETUP + r"""
const source={id:'browser-source',name:'Browser use',endpoint:'http://127.0.0.1/events',
  events:['task.completed','task.failed'],credentials:[],revoked:false,enabled:true,
  validated:true,outstanding:0,managed_tool:'browser_use'};
const card=controls.sourceCard(source,true);
assert.match(card.children[3].textContent,/Settings → Tools/);
assert.equal(card.querySelectorAll('button').length,0);
assert.equal(card.children[4].children[0].textContent,'Advanced delivery history');
const requests=[];
sandbox.Utils.auth.fetch=async url=>{
  requests.push(url);
  return {ok:true,json:async()=>({deliveries:[],total:0})};
};
const deliveries=card.children[4], output=deliveries.children[1];
deliveries.open=true;
deliveries.toggle();
await new Promise(resolve=>setTimeout(resolve,0));
assert.equal(requests[0],'/api/task-integrations/browser-source/deliveries?offset=0&limit=25');
assert.equal(output.children[0].textContent,'No deliveries on this page.');
""")
