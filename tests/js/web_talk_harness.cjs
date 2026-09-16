const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const root = process.cwd();
const scenario = process.argv[2];
const flush = async () => { for (let i = 0; i < 8; i++) await Promise.resolve(); };
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
let clock = 0, sequence = 0, amplitude = 0;
const document = {hidden:false, getElementById: name => elements[name], addEventListener:(event,fn) => docEvents[event]=fn};
const socket = {
  connected:true, mode:'local', conversationId:'a',
  on(event,fn){(socketEvents[event] ||= []).push(fn);},
  cancel(cid,id){cancelled.push([cid,id]);return true;}
};
function emit(event, data) { for (const fn of socketEvents[event] || []) fn(data); }
function stream() { const track = {enabled:true, stops:0, stop(){this.stops++;}}; tracks.push(track); return {getTracks:()=>[track],getAudioTracks:()=>[track]}; }
class Recorder {
  static isTypeSupported(type) {return type==='audio/webm;codecs=opus';}
  constructor(stream,options) {this.state='inactive';this.mimeType=options?.mimeType||'audio/webm'; recorders.push(this);}
  start(){this.state='recording';}
  stop(){this.state='inactive';queueMicrotask(()=>{this.ondataavailable?.({data:new Blob([new Uint8Array(6000)],{type:this.mimeType})});this.onstop?.();});}
}
class Context {
  constructor(){this.state='suspended';this.sources=[];contexts.push(this);}
  async resume(){this.state='running';}
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
const app = {_cancelStatusTTS(){},stopAudioPlayback(){}};
const sandbox = {
  console, Blob, FormData, AbortController, DOMException, URL, Float32Array, MediaRecorder:Recorder,
  navigator:{mediaDevices:{getUserMedia(){const p=deferred();permissions.push(p);return p.promise;}}},
  document, performance:{now:()=>clock},
  setInterval(fn){const id=++sequence;intervals.set(id,fn);return id;},clearInterval(id){intervals.delete(id);},
  setTimeout(fn,ms){const id=++sequence;timers.set(id,{fn,ms});return id;},clearTimeout(id){timers.delete(id);},
  Utils:{toast(...args){notices.push(args);},auth:{fetch(url, options){const p=deferred();requests.push({...p,url,options});return p.promise;}}},
  window:{location:{href:'https://jarvis.test/',origin:'https://jarvis.test'},AudioContext:Context,MediaRecorder:Recorder,addEventListener:(event,fn)=>windowEvents[event]=fn}
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(`${root}/jarvis-web/client/js/talk.js`,'utf8'),sandbox);
const talk = new sandbox.window.TalkController({app,chat,socket});
async function start(){const pending=talk.start();await flush();permissions.at(-1).resolve(stream());await pending;assert.equal(talk.session.phase,'listening');}
function tick(rms,ms){amplitude=rms;for(let i=0;i<ms/50;i++){clock+=50;for(const fn of [...intervals.values()])fn();}}
function finishTimers(){for(const [id,item] of [...timers])if(item.ms===350){timers.delete(id);item.fn();}}
async function utterance(){tick(.04,500);tick(0,1300);await flush();assert.equal(requests.at(-1).url,'/api/stt');}
async function transcribe(text='What time is it?'){requests.at(-1).resolve({ok:true,json:async()=>({ok:true,text})});await flush();}
function settle(status='completed', id='r1'){chat.isProcessing=false;emit('runState',{conversation_id:'a',message_id:id,status});}
async function answer(data={}){emit('response',{message_id:'r1',conversation_id:'a',ok:true,speech:'It is noon.',...data});await flush();}
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
    assert.equal(talk.active,false);assert.equal(cancelled.length,0);socket.connected=true;emit('connectionChange',{connected:true});await answer();assert.equal(requests.length,1);assert(talk.ownsResponse({message_id:'r1'}));
  } else if(scenario==='hidden') {
    await start();document.hidden=true;docEvents.visibilitychange();assert.equal(talk.active,false);assert.equal(tracks[0].stops,1);document.hidden=false;docEvents.visibilitychange();assert.equal(permissions.length,1);
  } else if(scenario==='denied') {
    const pending=talk.start();await flush();permissions[0].reject(Object.assign(Error('denied'),{name:'NotAllowedError'}));await pending;
    assert.equal(talk.session.phase,'paused');assert.equal(contexts[0].state,'closed');assert(elements.talkStatus.textContent.includes('denied'));
  } else if(scenario==='no_speech') {
    await start();await utterance();await transcribe('  ');assert.equal(sent.length,0);assert.equal(talk.session.phase,'paused');
  } else if(scenario==='voice_end') {
    await start();await utterance();await transcribe('End talk.');assert.equal(sent.length,0);assert.equal(talk.active,false);
  } else if(scenario==='tts_failure') {
    await start();await utterance();await transcribe();settle();await answer();requests.at(-1).resolve({ok:false,status:503,json:async()=>({error:'TTS unavailable'})});await flush();assert.equal(talk.session.phase,'paused');assert(elements.talkStatus.textContent.includes('TTS unavailable'));
  } else if(scenario==='stt_timeout') {
    await start();await utterance();const request=requests.at(-1);const timer=[...timers.values()].find(x=>x.ms===90000);timer.fn();request.reject(new DOMException('aborted','AbortError'));await flush();assert.equal(talk.session.phase,'paused');assert(elements.talkStatus.textContent.includes('timed out'));
  } else if(scenario==='interrupt_work') {
    await start();await utterance();await transcribe();talk.interrupt();assert.equal(talk.session.phase,'stopping');assert.equal(recorders.length,1);await answer();assert.equal(requests.length,1);settle('cancelled');finishTimers();assert.equal(talk.session.phase,'listening');assert.equal(cancelled.length,1);
  } else if(scenario==='interrupt_tts') {
    await start();await utterance();await transcribe();await answer();const pending=requests.at(-1);talk.interrupt();assert(pending.options.signal.aborted);await audio();assert.equal(contexts[0].sources.length,0);settle('cancelled');finishTimers();assert.equal(talk.session.phase,'listening');
  } else if(scenario==='pause_pending') {
    await start();await utterance();await transcribe();talk.pause();await answer();assert.equal(requests.length,1);settle();assert.equal(talk.session.phase,'paused');
    const pending=talk.resume();await flush();permissions.at(-1).resolve(stream());await pending;assert.equal(talk.session.phase,'listening');
  } else if(scenario==='saved_audio') {
    await start();await utterance();await transcribe();settle();await answer({audio_url:'/audio/tts/answer.mp3'});assert.equal(requests.at(-1).url,'https://jarvis.test/audio/tts/answer.mp3');await audio();contexts[0].sources[0].onended();await flush();finishTimers();assert.equal(talk.session.phase,'listening');
  } else if(scenario==='duplicate') {
    await start();await utterance();await transcribe();await answer();await answer();assert.equal(requests.length,2);await audio();talk.end();assert.equal(contexts[0].sources[0].stopped,true);await answer();assert.equal(requests.length,2);
  } else if(scenario==='draft') {
    chat.inputField.value='unsent';await talk.start();assert.equal(permissions.length,0);assert.equal(chat.inputField.value,'unsent');assert(notices[0][0].includes('draft'));
  } else if(scenario==='device_loss') {
    await start();tracks[0].onended();assert.equal(talk.session.phase,'paused');assert.equal(intervals.size,0);assert.equal(contexts[0].state,'closed');
  } else if(scenario==='new_conversation') {
    socket.conversationId=null;await start();await utterance();await transcribe();socket.conversationId='a';emit('conversationCreated',{conversation_id:'a'});assert.equal(talk.session.conversationId,'a');settle();await answer();await audio();contexts[0].sources[0].onended();await flush();finishTimers();assert.equal(talk.session.phase,'listening');
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
    await start();chat.isProcessing=true;emit('runState',{conversation_id:'a',message_id:'other',status:'running'});
    assert.equal(talk.session.phase,'paused');await talk.resume();assert.equal(permissions.length,1);
    chat.isProcessing=false;const pending=talk.resume();await flush();permissions.at(-1).resolve(stream());await pending;assert.equal(talk.session.phase,'listening');
  } else if(scenario==='composer_restore') {
    chat.uploadBtn.disabled=true;await start();assert.equal(chat.inputField.readOnly,true);talk.end();
    assert.equal(chat.uploadBtn.disabled,true);assert.equal(chat.micBtn.disabled,false);
    assert.equal(notices.length,0); // Ending must not cover the composer with a toast.
  } else {throw Error(`unknown scenario ${scenario}`);}
  talk.end('',{cancel:false});
  await flush();
  assert.equal(intervals.size,0);
  assert(contexts.every(c=>c.state==='closed'));
  assert(tracks.every(t=>t.stops===1));
  console.log('passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
