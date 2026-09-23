"""Talk lifecycle uses actual controller code with deterministic audio/network edges."""
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('scenario', [
    'warmup', 'loop', 'silence', 'noise', 'max_recording', 'late_permission', 'late_stt',
    'switch', 'disconnect', 'hidden', 'denied', 'no_speech', 'voice_end',
    'tts_failure', 'stt_timeout', 'interrupt_work', 'interrupt_tts',
    'pause_pending', 'saved_audio', 'duplicate', 'draft', 'device_loss', 'new_conversation',
    'other_task', 'composer_restore',
    'resume_permission_pending', 'resume_work_pending',
])
def test_talk_lifecycle(scenario):
    result = subprocess.run(
        ['node', str(ROOT / 'tests/js/web_talk_harness.cjs'), scenario],
        cwd=ROOT, capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'passed' in result.stdout


def test_talk_uses_real_composer_and_socket_payload():
    from test_web_voice_dictation import run_browser

    run_browser(r"""
const socketSource = fs.readFileSync(ROOT + '/jarvis-web/client/js/socket.js', 'utf8');
const Socket = vm.runInContext(socketSource.slice(0, socketSource.lastIndexOf('// Create global instance')) + '\nJarvisSocket;', sandbox);
sandbox.crypto = require('node:crypto').webcrypto;
const payloads = [];
const realSocket = Object.create(Socket.prototype);
Object.assign(realSocket, {connected:true, mode:'local', socket:{emit:(event,data)=>payloads.push([event,data])}});
realSocket.conversationId = 'conversation-a';
sandbox.window.jarvisSocket = realSocket;
ui._talkActive = true;
ui.chatOnlyEnabled = true;
ui.feedbackEnabled = true;
ui.selectedToolHints = ['get_time'];
ui.addUserMessage = text => ({text});
ui.rememberRenderedMessage = (...args) => { ui.rendered = args; };
const id = ui.sendTalkMessage('What time is it?');
assert.equal(payloads.length,1);
const [event,payload] = payloads[0];
assert.equal(event,'chat:send');
assert.equal(payload.input_mode,'talk');
assert.equal(payload.tool_policy,'none');
assert.equal(payload.request_feedback,undefined);
assert.equal(payload.conversation_id,'conversation-a');
assert.equal(payload.mode,'local');
assert.equal(payload.request_id,id);
assert.equal(payload.tool_hints[0],'get_time');
assert.equal(ui._pendingSend.text,'What time is it?');
assert.equal(ui.sendTalkMessage('duplicate'),null);
assert.equal(payloads.length,1);
await ui.sendMessage();
assert.equal(payloads.length,1);
ui._talkActive=false;ui.isProcessing=false;
assert.equal(ui.sendTalkMessage('no session'),null);
realSocket.sendMessage('ordinary text');
assert.equal(payloads[1][1].input_mode,undefined);
""")


def test_app_audio_is_owned_once_and_ordinary_audio_still_works():
    from test_web_voice_dictation import run_browser

    run_browser(r"""
const source = fs.readFileSync(ROOT + '/jarvis-web/client/js/app.js','utf8');
const App = vm.runInContext(source + '\nJarvisApp;',sandbox);
const app = Object.create(App.prototype);
const played = [], generated = [];
Object.assign(app, {socket, audioEnabled:true, _completedResponseIds:new Set(),
  talk:{active:false,ownsResponse:data=>data.message_id==='talk-owned'},
  _cancelStatusTTS(){}, _loadConversationHistory(){},
  _playAudio:(...args)=>played.push(args), _generateAndPlayTTS:(...args)=>generated.push(args)});
app._setupSocketListeners();
socketHandlers.response({message_id:'talk-owned',audio_url:'/audio/owned.mp3',speech:'Owned answer'});
assert.equal(played.length,0);assert.equal(generated.length,0);
app.talk.active=true;
socketHandlers.response({message_id:'other',audio_url:'/audio/other.mp3'});
assert.equal(played.length,0);
app.talk.active=false;
socketHandlers.response({message_id:'text-a',audio_url:'/audio/text.mp3'});
assert.equal(played.length,1);
socketHandlers.response({message_id:'text-b',speech:'Normal answer'});
assert.equal(generated.length,1);
assert.equal(app.audioEnabled,true);
""")


def test_app_tts_warmup_is_authenticated_mode_scoped_and_nonfatal():
    from test_web_voice_dictation import run_browser

    run_browser(r"""
const source = fs.readFileSync(ROOT + '/jarvis-web/client/js/app.js','utf8');
const App = vm.runInContext(source + '\nJarvisApp;',sandbox);
const app = Object.create(App.prototype);
const calls=[];
sandbox.Utils.auth.fetch=async(url,options)=>{calls.push([url,options]);return {ok:true};};
assert.equal(await app._warmTTS('local'),true);
assert.equal(calls[0][0],'/api/tts/warmup');
assert.equal(calls[0][1].method,'POST');
assert.deepEqual(JSON.parse(calls[0][1].body),{mode:'local'});
sandbox.Utils.auth.fetch=async()=>{throw Error('offline');};
assert.equal(await app._warmTTS('cloud'),false);
""")


@pytest.mark.parametrize('body_pending', [False, True])
def test_normal_tts_pending_before_talk_cannot_play_after_talk_ends(body_pending):
    from test_web_voice_dictation import run_browser

    run_browser("const bodyPending = " + str(body_pending).lower() + r""";
const source = fs.readFileSync(ROOT + '/jarvis-web/client/js/app.js','utf8');
const App = vm.runInContext(source + '\nJarvisApp;',sandbox);
const app=Object.create(App.prototype), network=deferred(), body=deferred(), played=[];
Object.assign(app,{socket,talk:{active:false},_playAudio:(...args)=>played.push(args)});
sandbox.fetch=()=>network.promise;
const pending=app._generateAndPlayTTS('The previous answer.');
if(bodyPending){network.resolve({ok:true,headers:{get:()=> 'audio/mpeg'},blob:()=>body.promise});await flush();}
app._talkAudioEpoch=1; // A complete Talk start/end happened during this request.
network.resolve({ok:true,headers:{get:()=> 'audio/mpeg'},blob:()=>body.promise});
body.resolve(new Blob(['audio']));await pending;
assert.equal(played.length,0);
""")
