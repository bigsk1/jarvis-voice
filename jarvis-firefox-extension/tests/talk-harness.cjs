const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const root = require('node:path').resolve(__dirname, '..');
const scenario = process.argv[2];
const state = {connection:{status:'connected'}, capabilities:{talk:true}, settings:{serverUrl:'https://jarvis.test'}, mode:'local', conversationId:'a', run:null};
const flush = async () => { for (let i = 0; i < 32; i++) await Promise.resolve(); };
function deferred() { let resolve, reject; const promise = new Promise((yes,no) => {resolve=yes;reject=no;}); return {promise,resolve,reject}; }
class Element {
  constructor() { this.hidden = false; this.disabled = false; this.value = ''; this.dataset = {}; this.events = {}; this.attributes = {}; this.classList = {toggle(){}, contains(){return false;}}; }
  addEventListener(event, fn) { (this.events[event] ||= []).push(fn); }
  setAttribute(name, value) { this.attributes[name] = value; }
  focus() {}
}
const elements = Object.fromEntries(['talkBtn','talkPanel','talkStatus','talkTranscript','talkPause','talkInterrupt','talkEnd','convertBtn'].map(name => [name, new Element()]));
const docEvents = {}, windowEvents = {}, socketEvents = {};
const requests = [], permissions = [], recorders = [], contexts = [], tracks = [], notices = [], sent = [], cancelled = [];
const intervals = new Map(), timers = new Map();
let clock = 0, sequence = 0, amplitude = 0, microphoneOpened = false;
const document = {hidden:false, getElementById: name => elements[name], addEventListener:(event,fn) => docEvents[event]=fn};
const socket = {
  connected:true, mode:'local', conversationId:'a',
  on(event,fn){(socketEvents[event] ||= []).push(fn);},
  cancel(cid,id){cancelled.push([cid,id]);return true;}
};
function emit(event, data) {
  if(event==='conversationCreated'){state.conversationId=data.conversation_id;talk.update(state);return;}
  if(event==='modeChanged'){state.mode='cloud';talk.update(state);return;}
  if(event==='connectionChange'){state.connection.status=data.connected?'connected':'disconnected';talk.update(state);return;}
  talk.event(({response:'chat:response',runState:'chat:run',error:'chat:error',rejected:'chat:rejected',cancelled:'chat:cancelled'})[event],data);
}
function stream() { microphoneOpened = true; const track = {enabled:true, stops:0, stop(){this.stops++;}}; tracks.push(track); return {getTracks:()=>[track],getAudioTracks:()=>[track]}; }
class Recorder {
  static isTypeSupported(type) {return type==='audio/webm;codecs=opus';}
  constructor(stream,options) {this.state='inactive';this.mimeType=options?.mimeType||'audio/webm'; recorders.push(this);}
  start(){this.state='recording';}
  stop(){this.state='inactive';queueMicrotask(()=>{this.ondataavailable?.({data:new Blob([new Uint8Array(6000)],{type:this.mimeType})});this.onstop?.();});}
}
class Context {
  constructor(){this.state='suspended';this.sources=[];contexts.push(this);}
  async resume(){
    if (scenario==='audio_timeout' || scenario==='audio_after_microphone' && !microphoneOpened) return new Promise(()=>{});
    this.state='running';
  }
  async close(){this.state='closed';}
  createMediaStreamSource(){return {connect(){},disconnect(){}};}
  createAnalyser(){return {fftSize:2048,disconnect(){},getFloatTimeDomainData(array){array.fill(amplitude);}};}
  async decodeAudioData(bytes){if(!bytes.byteLength)throw Error('empty audio');return {duration:1};}
  createBufferSource(){const source={connect(){},disconnect(){},start(){source.started=true;},stop(){source.stopped=true;source.onended?.();}};this.sources.push(source);return source;}
}
const chat = {
  inputField:new Element(), micBtn:new Element(), uploadBtn:new Element(), enhanceBtn:new Element(),
  attachedDocuments:[],attachedImages:[],isProcessing:false,updateSendButton(){},
  sendTalkMessage(text){sent.push(text);chat.isProcessing=true;return `r${sent.length}`;}
};
const sandbox = {
  console, Blob, FormData, AbortController, DOMException, URL, Float32Array, crypto:require('node:crypto').webcrypto, MediaRecorder:Recorder,
  navigator:{mediaDevices:{getUserMedia(){const p=deferred();permissions.push(p);return p.promise;}}},
  document, performance:{now:()=>clock},
  setInterval(fn){const id=++sequence;intervals.set(id,fn);return id;},clearInterval(id){intervals.delete(id);},
  setTimeout(fn,ms){const id=++sequence;timers.set(id,{fn,ms});return id;},clearTimeout(id){timers.delete(id);},
  window:{location:{href:'https://jarvis.test/',origin:'https://jarvis.test'},AudioContext:Context,MediaRecorder:Recorder,addEventListener:(event,fn)=>windowEvents[event]=fn}
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(`${root}/ui/talk.js`,'utf8').replace(/export /g,'')+'\nglobalThis.TalkController=TalkController;',sandbox);
const rpc = async(sessionId,action,payload={},signal) => {
  if(action==='claim')return;
  if(action==='release'){if(payload.cancel&&talkTurn&&!talkTurn.settled)cancelled.push(talkTurn.id);return;}
  if(action==='cancel'){cancelled.push(talk.session.turn.id);return;}
  if(action==='send'){
    sent.push(payload.text);state.run={messageId:payload.requestId,status:'running'};talkTurn=talk.session.turn;return payload.requestId;
  }
  const p=deferred();requests.push({...p,url:action==='audio'?'https://jarvis.test/audio/tts/answer.mp3':'/api/'+action,options:{signal},action,payload});
  return p.promise.then(async response=>{if(!response.ok)throw Error((await response.json()).error);return action==='stt'?response.json():response.arrayBuffer();});
};
let talkTurn=null;
const talk = new sandbox.TalkController({getState:()=>state,rpc,hasDraft:()=>Boolean(chat.inputField.value),notify:(msg)=>notices.push([msg]),render:s=>{elements.talkStatus.textContent=s?.message||s?.phase||'';}});
async function start(){const pending=talk.start();await flush();permissions.at(-1).resolve(stream());await pending;assert.equal(talk.session.phase,'listening');}
function tick(rms,ms){amplitude=rms;for(let i=0;i<ms/50;i++){clock+=50;for(const fn of [...intervals.values()])fn();}}
function finishTimers(){for(const [id,item] of [...timers])if(item.ms===350){timers.delete(id);item.fn();}}
async function utterance(){tick(.04,500);tick(0,1300);await flush();assert.equal(requests.at(-1).url,'/api/stt');}
async function transcribe(text='What time is it?'){requests.at(-1).resolve({ok:true,json:async()=>({ok:true,text})});await flush();}
function settle(status='completed', id=talk.session.turn.id){state.run={messageId:id,status};emit('runState',{conversation_id:'a',message_id:id,status});}
async function answer(data={}){emit('response',{message_id:talk.session?.turn?.id||state.run?.messageId,conversation_id:'a',ok:true,speech:'It is noon.',...data});await flush();}
async function audio(){requests.at(-1).resolve({ok:true,arrayBuffer:async()=>new Uint8Array([1,2]).buffer});await flush();}
(async()=>{
  if(scenario==='loop') {
    await start();await utterance();assert.equal(tracks[0].enabled,false);await transcribe();
    assert.equal(sent.length,1);await answer();assert.equal(requests.at(-1).url,'/api/tts');await audio();
    contexts[0].sources[0].onended();await flush();assert.equal(talk.session.phase,'speaking'); // task not settled
    settle();finishTimers();assert.equal(talk.session.phase,'listening');assert.equal(tracks[0].enabled,true);
    await utterance();await transcribe('And tomorrow?');assert.deepEqual(sent,['What time is it?','And tomorrow?']);
    talk.end();assert.equal(cancelled.length,1);assert.equal(tracks[0].stops,1);
  } else if(scenario==='silence') {
    await start();tick(0,30100);assert.equal(talk.session.phase,'paused');assert.equal(requests.length,0);assert.equal(tracks[0].stops,1);
  } else if(scenario==='noise') {
    await start();for(let i=0;i<50;i++){tick(.04,100);tick(0,500);}assert.equal(requests.length,0);assert.equal(talk.session.phase,'paused');
  } else if(scenario==='max_recording') {
    await start();tick(.04,45100);await flush();assert.equal(requests.length,1);assert.equal(talk.session.phase,'transcribing');
  } else if(scenario==='late_permission') {
    const pending=talk.start();await flush();talk.end();const s=stream();permissions[0].resolve(s);await pending;
    assert.equal(s.getTracks()[0].stops,1);assert.equal(recorders.length,0);assert.equal(contexts[0].state,'closed');
  } else if(scenario==='late_stt') {
    await start();await utterance();talk.end();await transcribe();assert.equal(sent.length,0);assert.equal(requests[0].options.signal.aborted,true);
  } else if(scenario==='switch') {
    await start();await utterance();socket.mode='cloud';emit('modeChanged',{mode:'cloud'});await transcribe();assert.equal(sent.length,0);assert.equal(talk.active,false);
  } else if(scenario==='disconnect') {
    await start();await utterance();await transcribe();socket.connected=false;emit('connectionChange',{connected:false});
    assert.equal(talk.active,false);assert.equal(cancelled.length,0);socket.connected=true;emit('connectionChange',{connected:true});await answer();assert.equal(requests.length,1);
  } else if(scenario==='hidden') {
    await start();document.hidden=true;talk.end('',{cancel:false});assert.equal(talk.active,false);assert.equal(tracks[0].stops,1);document.hidden=false;talk.end('',{cancel:false});assert.equal(permissions.length,1);
  } else if(scenario==='denied') {
    const pending=talk.start();await flush();permissions[0].reject(Object.assign(Error('denied'),{name:'NotAllowedError'}));await pending;
    assert.equal(talk.session.phase,'paused');assert.equal(contexts[0].state,'closed');assert(elements.talkStatus.textContent.includes('Microphone setup'));
  } else if(scenario==='audio_after_microphone') {
    const pending=talk.start();await flush();assert.equal(permissions.length,1,'Suspended playback must not block microphone permission');
    permissions[0].resolve(stream());await pending;assert.equal(talk.session.phase,'listening');
  } else if(scenario==='permission_timeout' || scenario==='audio_timeout') {
    const pending=talk.start();await flush();
    if(scenario==='audio_timeout'){permissions[0].resolve(stream());await flush();}
    const timeout=scenario==='permission_timeout'?30000:8000;
    for(const [id,item] of [...timers])if(item.ms===timeout){timers.delete(id);item.fn();}
    await pending;assert.equal(talk.session.phase,'paused');assert.equal(contexts[0].state,'closed');
    if(scenario==='permission_timeout'){permissions[0].resolve(stream());await flush();assert.equal(tracks[0].stops,1);}
    assert.equal(recorders.length,0);
  } else if(scenario==='pause_preparing') {
    const pending=talk.start();talk.pause();await pending;
    assert.equal(permissions.length,0);assert.equal(talk.session.phase,'paused');
  } else if(scenario==='no_speech') {
    await start();await utterance();await transcribe('  ');assert.equal(sent.length,0);assert.equal(talk.session.phase,'paused');
  } else if(scenario==='voice_end') {
    await start();await utterance();await transcribe('End talk.');assert.equal(sent.length,0);assert.equal(talk.active,false);
  } else if(scenario==='tts_failure') {
    await start();await utterance();await transcribe();settle();await answer();requests.at(-1).resolve({ok:false,status:503,json:async()=>({error:'TTS unavailable'})});await flush();assert.equal(talk.session.phase,'paused');assert(elements.talkStatus.textContent.includes('TTS unavailable'));
  } else if(scenario==='interrupt_work') {
    await start();await utterance();await transcribe();talk.interrupt();assert.equal(talk.session.phase,'stopping');assert.equal(recorders.length,1);await answer();assert.equal(requests.length,1);settle('cancelled');finishTimers();assert.equal(talk.session.phase,'listening');assert.equal(cancelled.length,1);
  } else if(scenario==='interrupt_tts') {
    await start();await utterance();await transcribe();await answer();const pending=requests.at(-1);talk.interrupt();assert(pending.options.signal.aborted);await audio();assert.equal(contexts[0].sources.length,0);settle('cancelled');finishTimers();assert.equal(talk.session.phase,'listening');
  } else if(scenario==='pause_pending') {
    await start();await utterance();await transcribe();talk.pause();await answer();assert.equal(requests.length,1);settle();assert.equal(talk.session.phase,'paused');
    const pending=talk.resume();await flush();permissions.at(-1).resolve(stream());await pending;assert.equal(talk.session.phase,'listening');
  } else if(scenario==='saved_audio') {
    await start();await utterance();await transcribe();settle();await answer({audio_url:'/audio/tts/answer.mp3'});assert.equal(requests.at(-1).url,'https://jarvis.test/audio/tts/answer.mp3');await audio();contexts[0].sources[0].onended();await flush();finishTimers();assert.equal(talk.session.phase,'listening');
  } else if(scenario==='background_result') {
    await start();await utterance();await transcribe();
    const before=talk.session.phase, requestCount=requests.length;
    talk.event('task:updated',{conversation_id:'a',message_id:talk.session.messageId,state:'succeeded'});
    talk.event('chat:continuation',{conversation_id:'a',message_id:talk.session.messageId,text:'Late result'});
    await flush();assert.equal(talk.session.phase,before);assert.equal(requests.length,requestCount);
    settle();await answer();await audio();contexts[0].sources[0].onended();await flush();finishTimers();
    assert.equal(talk.session.phase,'listening');
  } else if(scenario==='approval_denied' || scenario==='approval_timeout') {
    await start();await utterance();await transcribe();
    const decision = scenario === 'approval_denied' ? 'denied' : 'expired';
    settle('completed');assert.equal(talk.session.phase,'waiting');
    await answer({cancelled:true,approval_outcome:{tool:'api_call',decision},speech:decision === 'denied' ? 'You declined the call.' : 'The approval wait expired.'});
    assert.equal(talk.session.phase,'speaking');
    await audio();contexts[0].sources[0].onended();await flush();
    finishTimers();assert.equal(talk.session.phase,'listening');
  } else if(scenario==='approval_stop') {
    await start();await utterance();await transcribe();
    await answer({cancelled:true,approval_outcome:{tool:'api_call',decision:'cancelled'},speech:'Stopped before the call.'});
    settle('cancelled');assert.equal(talk.session.phase,'paused');
  } else if(scenario==='duplicate') {
    await start();await utterance();await transcribe();await answer();await answer();assert.equal(requests.length,2);await audio();talk.end();assert.equal(contexts[0].sources[0].stopped,true);await answer();assert.equal(requests.length,2);
  } else if(scenario==='draft') {
    chat.inputField.value='unsent';await talk.start();assert.equal(permissions.length,0);assert.equal(chat.inputField.value,'unsent');assert(notices[0][0].includes('draft'));
  } else if(scenario==='device_loss') {
    await start();tracks[0].onended();assert.equal(talk.session.phase,'paused');assert.equal(intervals.size,0);assert.equal(contexts[0].state,'closed');
  } else if(scenario==='new_conversation') {
    state.conversationId=null;await start();await utterance();await transcribe();socket.conversationId='a';emit('conversationCreated',{conversation_id:'a'});assert.equal(talk.session.conversationId,'a');settle();await answer();await audio();contexts[0].sources[0].onended();await flush();finishTimers();assert.equal(talk.session.phase,'listening');
  } else if(scenario==='resume_permission_pending' || scenario==='resume_work_pending') {
    await start();await utterance();await transcribe();talk.pause();
    const pending=talk.resume();await flush();
    if(scenario==='resume_work_pending'){permissions.at(-1).resolve(stream());await pending;assert.equal(talk.session.phase,'waiting');}
    await answer();settle();finishTimers();assert.equal(requests.length,1); // paused turn must remain silent
    if(scenario==='resume_permission_pending'){
      assert.equal(talk.session.phase,'preparing');assert.equal(recorders.length,1);
      permissions.at(-1).resolve(stream());await pending;
    }
    assert.equal(talk.session.phase,'listening');assert.equal(recorders.length,2);
  } else if(scenario==='other_task') {
    await start();state.run={messageId:'other',status:'running'};emit('runState',{conversation_id:'a',message_id:'other',status:'running'});
    assert.equal(talk.session.phase,'paused');await talk.resume();assert.equal(permissions.length,1);
    state.run.status='completed';const pending=talk.resume();await flush();permissions.at(-1).resolve(stream());await pending;assert.equal(talk.session.phase,'listening');
  } else {throw Error(`unknown scenario ${scenario}`);}
  talk.end('',{cancel:false});
  await flush();
  assert.equal(intervals.size,0);
  assert(contexts.every(c=>c.state==='closed'));
  assert(tracks.every(t=>t.stops===1));
  console.log('passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
