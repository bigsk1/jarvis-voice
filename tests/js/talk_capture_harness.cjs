// Execute the shipped AudioWorklet processor and PCM encoder with synthetic audio.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = path.resolve(__dirname, '../..');
const web = path.join(root, 'jarvis-web/client/js');
for (const name of ['talk-capture.js', 'talk-capture-worklet.js']) {
  assert.equal(fs.readFileSync(path.join(web, name), 'utf8'),
    fs.readFileSync(path.join(root, 'jarvis-firefox-extension/ui', name), 'utf8'));
}
let Processor;
const messages = [];
const sandbox = {sampleRate:16000, Float32Array,
  AudioWorkletProcessor: class {constructor(){this.port={postMessage:data=>messages.push(data)};}},
  registerProcessor(name, constructor){assert.equal(name,'jarvis-talk-capture');Processor=constructor;},
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(web,'talk-capture-worklet.js'),'utf8'), sandbox);
function processor() {
  messages.length=0;
  const p=new Processor();p.port.onmessage({data:{type:'arm',token:7}});return p;
}
function feed(p,ms,mic=()=>0,reference=()=>0) {
  for(let frame=0;frame<ms/20;frame++) {
    const at=p.clock*16;
    const m=Float32Array.from({length:320},(_,i)=>mic(at+i));
    const r=Float32Array.from({length:320},(_,i)=>reference(at+i));
    const output=new Float32Array(320).fill(1);
    p.process([[m],[r]],[[output]]);
    assert(output.every(value=>value===0),'microphone must never play through speakers');
  }
}
const voice=i=>(.035+.02*Math.sin(i*.0017))*Math.sin(i*.14);
const assistant=i=>(.11+.08*Math.sin(i*.00063))*Math.sin(i*.23);
const count=type=>messages.filter(m=>m.type===type).length;
let p=processor();feed(p,2000);assert.equal(messages.length,0);
feed(p,100,voice);feed(p,1500);assert.equal(count('speech-start'),0,'brief noise must not interrupt');
p=processor();feed(p,1400,i=>assistant(i-1280)*.5,assistant);
assert.equal(count('speech-start'),0,'delayed attenuated playback echo must not interrupt');
// Independent user speech must still trigger over audible playback.
feed(p,700,i=>voice(i)+assistant(i-1280)*.08,assistant);
assert.equal(count('speech-start'),1);
feed(p,1400,i=>assistant(i-1280)*.08,assistant);
assert.equal(count('speech-end'),1);
const captured=messages.filter(m=>m.type==='samples').flatMap(m=>Array.from(m.samples));
assert(captured.some(v=>Math.abs(v)>.02));
assert(captured.length<=16000*3);
// An immediate interruption keeps the onset while the detector waits for attack.
p=processor();feed(p,700,voice);assert.equal(count('speech-start'),1);
const first=messages.find(m=>m.type==='samples').samples;
assert(Math.abs(first[1]-voice(1))<1e-6,'pre-roll must preserve first syllable');
feed(p,1400);assert.equal(count('speech-end'),1);
p=processor();feed(p,500,voice);p.port.onmessage({data:{type:'disarm'}});
feed(p,3000,voice);assert.equal(count('speech-end'),0);
p=processor();feed(p,46400,voice);assert.equal(count('speech-end'),1,'continuous sound must hit recording limit');
// Actual browser render quanta need not divide a 20 ms analysis frame.
for (const rate of [44100,48000]) {
  sandbox.sampleRate=rate;p=processor();let offset=0;
  for(let quantum=0;quantum<Math.ceil(rate*2.1/128);quantum++) {
    const mic=Float32Array.from({length:128},(_,i)=>offset+i<rate*.7?voice(offset+i):0);
    p.process([[mic],[]],[[new Float32Array(128)]]);offset+=128;
  }
  assert.equal(count('speech-start'),1);assert.equal(count('speech-end'),1);
}

// Real helper: module caching, reference wiring, bounded WAV, stale-message cleanup.
(async()=>{
  const nodes=[], wiring=[];let loads=0, starts=0, blob;
  class Node {
    constructor(){nodes.push(this);this.port={postMessage(){},close(){this.closed=true;}};}
    connect(){wiring.push('silent-output');} disconnect(){wiring.push('disconnect');}
  }
  const helper={Blob, Float32Array, ArrayBuffer, DataView, WeakMap, AudioWorkletNode:Node,setTimeout,clearTimeout};
  vm.createContext(helper);vm.runInContext(fs.readFileSync(path.join(web,'talk-capture.js'),'utf8'),helper);
  const context={sampleRate:48000,destination:{},audioWorklet:{async addModule(){loads++;}}};
  const input={connect(){wiring.push('mic');},disconnect(){wiring.push('mic-disconnect');}};
  const source={connect(node,out,index){assert.equal(index,1);wiring.push('reference');},disconnect(){wiring.push('ref-disconnect');}};
  const callbacks={start(){starts++;},end(value){blob=value;},error(error){throw error;}};
  const capture=await helper.JarvisTalkCapture.create(context,input,'worklet',callbacks);
  capture.arm(source);const token=capture.token,node=nodes[0];
  node.port.onmessage({data:{type:'speech-start',token}});
  node.port.onmessage({data:{type:'samples',token,samples:new Float32Array(4800).fill(.25)}});
  node.port.onmessage({data:{type:'speech-end',token}});
  assert.equal(starts,1);assert.equal(blob.type,'audio/wav');
  const bytes=await blob.arrayBuffer(),view=new DataView(bytes);
  assert.equal(Buffer.from(bytes).subarray(0,4).toString(),'RIFF');
  assert.equal(view.getUint32(24,true),16000);assert.equal(view.getUint16(22,true),1);
  assert.equal(view.getUint32(40,true),3200);assert.equal(view.getInt16(44,true),8191);
  node.port.onmessage({data:{type:'speech-start',token}});assert.equal(starts,1,'disarmed token must be ignored');
  capture.close();assert.equal(node.port.onmessage,null);assert(wiring.includes('mic-disconnect'));
  const next=await helper.JarvisTalkCapture.create(context,input,'worklet',callbacks);assert.equal(loads,1);next.close();
  let failure;
  const failing=await helper.JarvisTalkCapture.create(context,input,'worklet',{...callbacks,error(error){failure=error;}});
  nodes.at(-1).onprocessorerror();assert.match(failure.message,/detector stopped/);failing.close();
  console.log('passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
