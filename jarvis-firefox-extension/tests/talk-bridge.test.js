import test from 'node:test';
import assert from 'node:assert/strict';
import {TalkBridge} from '../browser/talk.js';
import {TalkPort} from '../ui/talk-port.js';
import {JarvisClient} from '../core/client.js';
import {JarvisTransport} from '../core/transport.js';
const ORIGIN = 'https://jarvis.example';
const ID = '9c892f85-b79a-44c3-9be1-6b66d2f73145';
const tick = () => new Promise(resolve => setImmediate(resolve));
const deferred = () => {let resolve; const promise = new Promise(yes => {resolve = yes;}); return {promise, resolve};};

function harness(fetchImpl = async () => new Response(JSON.stringify({ok:true,text:'What time is it?'}))) {
  const writes = [], emitted = [], ports = [];
  let bridge, queue = Promise.resolve();
  const client = new JarvisClient({storage:{session:{set: async value => writes.push(structuredClone(value))}},
    onState: state => bridge?.observe(state), onServerEvent: (event,data) => bridge.event(event,data)});
  Object.assign(client.state, {connection:{status:'connected'}, mode:'local', capabilities:{talk:true}, conversationId:'c1'});
  client.state.settings.serverUrl = ORIGIN;
  client.transport = new JarvisTransport({serverUrl:ORIGIN,token:'test-token',fetchImpl});
  client.transport.socket = {connected:true,emit:(event,data)=>emitted.push({event,data})};
  bridge = new TalkBridge(client, fn => {queue=queue.catch(()=>{}).then(fn);return queue;}, message=>ports.forEach(port=>port.postMessage(message)));
  function port() {
    const p={messages:[],postMessage(message){this.messages.push(message);}};ports.push(p);bridge.attach(p);return p;
  }
  let n=0;
  function request(p,action,payload={},sessionId='talk-1') {
    const id=String(++n);bridge.handle(p,{type:'talk:request',id,sessionId,action,payload});return id;
  }
  async function rpc(p,action,payload={},sessionId='talk-1') {
    const id=request(p,action,payload,sessionId);
    for(let i=0;i<12;i++) {await tick();const reply=p.messages.find(m=>m.id===id);if(reply){if(!reply.ok)throw Error(reply.error);return reply.value;}}
    throw Error('Missing RPC reply');
  }
  const server=(event,data)=>{client.onEvent(event,data);bridge.event(event,data);};
  return {bridge,client,writes,emitted,port,request,rpc,server};
}

test('one view owns Talk; competitors cannot send, abort, or release its session', async()=>{
  const h=harness(), a=h.port(), b=h.port();await h.rpc(a,'claim');
  await assert.rejects(h.rpc(b,'claim',{},'talk-2'),/End Talk/);
  await assert.rejects(h.rpc(b,'send',{text:'wrong view',requestId:ID}),/Talk ended/);
  h.request(b,'release');assert.equal(h.bridge.owner.port,a);
  assert.throws(()=>h.bridge.requireIdle(),/End Talk/);
  h.bridge.detach(a);assert.equal(h.bridge.owner,null);assert.equal(h.emitted.length,0);
  await h.rpc(b,'claim',{},'talk-2');h.bridge.detach(b);
});

test('closing a view or ending a queued claim cannot resurrect its ownership',async()=>{
  const h=harness(),p=h.port();h.request(p,'claim');h.request(p,'release');await tick();
  assert.equal(h.bridge.owner,null);
  h.request(p,'claim',{},'talk-2');h.bridge.detach(p);await tick();assert.equal(h.bridge.owner,null);
});

test('Talk uses ordinary admission with its input mode and request ID; response audio stays ephemeral',async()=>{
  const h=harness(),p=h.port();await h.rpc(p,'claim');await h.rpc(p,'send',{text:'What time is it?',requestId:ID});
  const sent=h.emitted.find(e=>e.event==='chat:send').data;
  assert.equal(sent.input_mode,'talk');assert.equal(sent.request_id,ID);assert.equal(sent.mode,'local');assert.equal(sent.conversation_id,'c1');
  h.server('chat:response',{message_id:ID,conversation_id:'c1',text:'The time is noon.',speech:'Noon.',audio_url:'/audio/tts/noon.wav',ok:true});
  assert.equal(h.bridge.owner.settled,false,'A response alone does not rearm listening');
  assert.equal(p.messages.find(m=>m.event==='chat:response').data.speech,'Noon.');
  assert(!JSON.stringify(h.writes).includes('noon.wav'));
  h.server('chat:run',{message_id:ID,conversation_id:'c1',status:'completed'});
  assert.equal(h.bridge.owner.settled,true);h.bridge.detach(p);clearTimeout(h.client.recoveryTimer);
});

test('ending during the write-ahead checkpoint retains transcript without submitting work',async()=>{
  const h=harness(),p=h.port();await h.rpc(p,'claim');
  const gate=deferred();h.client.storage.session.set=()=>gate.promise;
  h.request(p,'send',{text:'Keep this transcript',requestId:ID});await tick();h.request(p,'release');gate.resolve();await tick();await tick();
  assert.equal(h.emitted.length,0);assert.equal(h.client.state.draft.text,'Keep this transcript');
});

test('closing after admission preserves server work; explicit End requests cancellation',async()=>{
  for(const close of [true,false]){
    const h=harness(),p=h.port();await h.rpc(p,'claim');await h.rpc(p,'send',{text:'Hello',requestId:ID});
    h.server('chat:thinking',{message_id:ID,conversation_id:'c1'});
    if(close)h.bridge.detach(p);else h.request(p,'release',{cancel:true});
    assert.equal(h.emitted.some(e=>e.event==='chat:cancel'),!close);clearTimeout(h.client.recoveryTimer);
  }
});

test('speech HTTP can be aborted while commands remain responsive; buffers are not stored',async()=>{
  const gate=deferred();let signal;
  const h=harness(async(url,options)=>{signal=options.signal;assert.equal(options.headers.Authorization,'Bearer test-token');return gate.promise;}),p=h.port();
  await h.rpc(p,'claim');const id=h.request(p,'stt',{bytes:new Uint8Array([1,2]).buffer,mimeType:'audio/ogg;codecs=opus'});await tick();
  h.request(p,'abort',{id});assert(signal.aborted);assert.equal(h.bridge.owner.request,null);
  gate.resolve(new Response(JSON.stringify({ok:true,text:'late question'})));await tick();await tick();
  assert.equal(p.messages.find(m=>m.id===id).ok,false);assert.equal(h.writes.length,0);h.bridge.detach(p);
});

test('changing authentication or transport ends Talk without cancelling accepted work',async()=>{
  const h=harness(),p=h.port();await h.rpc(p,'claim');h.client.authScope='changed';h.bridge.observe(h.client.state);
  assert.equal(h.bridge.owner,null);assert(p.messages.some(m=>m.type==='talk:ended'));assert.equal(h.emitted.length,0);
});

test('old servers and unsent content prevent Talk from acquiring the microphone',async()=>{
  const h=harness(),p=h.port();h.client.state.capabilities.talk=false;await assert.rejects(h.rpc(p,'claim'),/updated Jarvis/);
  h.client.state.capabilities.talk=true;h.client.state.draft.pageLink={url:'https://example.test'};
  await assert.rejects(h.rpc(p,'claim'),/draft/);assert.equal(h.bridge.owner,null);
});

test('binary speech transport uses the chosen mode and refuses foreign audio URLs',async()=>{
  const calls=[];const transport=new JarvisTransport({serverUrl:ORIGIN,token:'test-token',fetchImpl:async(url,options)=>{
    calls.push({url,options});return url.endsWith('/api/stt')?new Response(JSON.stringify({ok:true,text:'Hello'})):
      new Response(new Uint8Array([1,2,3]),{headers:{'Content-Type':'audio/wav'}});
  }});
  await transport.transcribe(new Uint8Array([1]).buffer,'audio/webm;codecs=opus','cloud');
  assert.equal(calls[0].options.body.get('mode'),'cloud');
  assert.equal(calls[0].options.headers['Content-Type'],undefined,'Browser supplies multipart boundary');
  const audio=await transport.synthesize('Hello','local',ID);assert.equal(audio.byteLength,3);
  assert.equal(JSON.parse(calls[1].options.body).mode,'local');
  assert.equal(calls[1].options.redirect,'error');assert.equal(calls[1].options.credentials,'omit');
  for(const url of ['https://other.test/audio/a.wav','//other.test/audio/a.wav','/api/auth/login','/audio/a.wav?token=x']) {
    await assert.rejects(transport.speech(url,{audio:true}),/not on this Jarvis server/);
  }
  assert.throws(()=>transport.transcribe(new ArrayBuffer(10*1024*1024+1),'audio/webm','local'),/too large/);
});

test('speech errors and non-audio responses are actionable',async()=>{
  const transport=new JarvisTransport({serverUrl:ORIGIN,fetchImpl:async()=>new Response('<html>oops</html>',{headers:{'Content-Type':'text/html'}})});
  await assert.rejects(transport.synthesize('Hi','local',ID),/unexpected audio/);
  transport.fetchImpl=async()=>new Response(JSON.stringify({error:'Speech unavailable'}),{status:503});
  await assert.rejects(transport.synthesize('Hi','local',ID),/Speech unavailable/);
});

test('the view bridge ignores late replies and aborts only its own pending request',async()=>{
  const messages=[],port={postMessage:message=>messages.push(message)},rpc=new TalkPort(()=>port),controller=new AbortController();
  const promise=rpc.request('one','stt',{},controller.signal);const id=messages[0].id;
  rpc.receive({type:'talk:reply',sessionId:'another',id,ok:true,value:'wrong'});assert.equal(rpc.pending.size,1);
  controller.abort();await assert.rejects(promise,/stopped/);assert.equal(messages.at(-1).action,'abort');
  rpc.receive({type:'talk:reply',sessionId:'one',id,ok:true,value:'late'});assert.equal(rpc.pending.size,0);
  const pending=rpc.request('two','claim');rpc.disconnect();await assert.rejects(pending,/disconnected/);
});

test('Interrupt and End during first-turn admission cancel after the conversation is assigned',async()=>{
  for(const end of [false,true]){
    const h=harness(),p=h.port();h.client.state.conversationId=null;
    await h.rpc(p,'claim');await h.rpc(p,'send',{text:'Hello',requestId:ID});
    if(end)h.request(p,'release',{cancel:true});else await h.rpc(p,'cancel');
    assert.equal(h.emitted.some(e=>e.event==='chat:cancel'),false);
    h.server('conversation:created',{conversation_id:'new'});
    h.server('chat:thinking',{message_id:ID,conversation_id:'new'});
    assert.deepEqual(h.emitted.find(e=>e.event==='chat:cancel').data,{conversation_id:'new',message_id:ID});
    h.bridge.detach(p);clearTimeout(h.client.recoveryTimer);
  }
});

test('another task and its reply cannot replace the speech belonging to a Talk turn',async()=>{
  const h=harness(),p=h.port();await h.rpc(p,'claim');await h.rpc(p,'send',{text:'Hello',requestId:ID});
  h.server('chat:response',{message_id:ID,conversation_id:'c1',speech:'Original answer.',ok:true});
  h.server('chat:run',{message_id:ID,conversation_id:'c1',status:'completed'});
  h.server('chat:run',{message_id:'guard-repair',conversation_id:'c1',status:'running'});
  h.server('chat:response',{message_id:'guard-repair',conversation_id:'c1',speech:'Separate repair answer.',ok:true});
  assert.equal(h.bridge.owner.answer.speech,'Original answer.');
  assert.equal(p.messages.filter(m=>m.event==='chat:response').at(-1).data.speech,undefined);
  assert(p.messages.some(m=>m.event==='chat:run'&&m.data.message_id==='guard-repair'));
  h.bridge.detach(p);clearTimeout(h.client.recoveryTimer);
});
