"""Browser lifecycle coverage for Web TTS audio blob URLs."""

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_tts_audio_blob_urls_are_revoked_on_every_terminal_path():
    script = r"""
const fs = require('fs');
const source = fs.readFileSync('jarvis-web/client/js/app.js', 'utf8');
const appSource = source.slice(
  source.indexOf('class JarvisApp'),
  source.indexOf('// Initialize app when DOM is ready')
);
eval(appSource + '\nglobal.JarvisApp = JarvisApp;');

const revoked = [];
const timers = [];
global.URL = {revokeObjectURL: (url) => revoked.push(url)};
global.Utils = {toast: () => {}};
global.document = {
  getElementById: () => ({style: {width: ''}})
};
global.setTimeout = (callback, delay) => {
  timers.push({callback, delay});
  return timers.length;
};

class FakeAudio {
  static instances = [];
  static rejectNextPlay = false;

  constructor(url) {
    this.src = url;
    this.currentTime = 0;
    this.duration = 1;
    this.ended = false;
    this.listeners = {};
    FakeAudio.instances.push(this);
  }

  addEventListener(name, callback) {
    this.listeners[name] = callback;
  }

  emit(name, event = {}) {
    this.listeners[name]?.(event);
  }

  pause() {
    this.paused = true;
  }

  play() {
    if (FakeAudio.rejectNextPlay) {
      FakeAudio.rejectNextPlay = false;
      return Promise.reject(new Error('autoplay blocked'));
    }
    return Promise.resolve();
  }
}
global.Audio = FakeAudio;

const app = Object.create(global.JarvisApp.prototype);
Object.assign(app, {
  currentAudio: null,
  currentAudioKind: null,
  currentAudioUrl: null,
  isPlaying: false,
  speakerBtn: null,
  _updateSpeakerButton: () => {}
});

const assertRevoked = (expected, message) => {
  if (JSON.stringify(revoked) !== JSON.stringify(expected)) {
    throw new Error(`${message}: ${JSON.stringify(revoked)}`);
  }
};

(async () => {
  app._playAudio('blob:first');
  app._playAudio('blob:second');
  assertRevoked(['blob:first'], 'replacement did not release the first URL');

  app.stopAudioPlayback();
  assertRevoked(
    ['blob:first', 'blob:second'],
    'manual stop did not release the current URL'
  );
  app.stopAudioPlayback();
  assertRevoked(
    ['blob:first', 'blob:second'],
    'manual stop cleanup was not idempotent'
  );

  app._playAudio('blob:error');
  FakeAudio.instances.at(-1).emit('error', new Error('decode failed'));
  assertRevoked(
    ['blob:first', 'blob:second', 'blob:error'],
    'audio error did not release its URL'
  );

  FakeAudio.rejectNextPlay = true;
  app._playAudio('blob:rejected');
  await new Promise(resolve => setImmediate(resolve));
  assertRevoked(
    ['blob:first', 'blob:second', 'blob:error', 'blob:rejected'],
    'play rejection did not release its URL'
  );

  app._playAudio('blob:ended');
  const endedAudio = FakeAudio.instances.at(-1);
  endedAudio.ended = true;
  endedAudio.emit('ended');
  assertRevoked(
    ['blob:first', 'blob:second', 'blob:error', 'blob:rejected'],
    'natural completion released the replay URL too early'
  );
  const replayExpiry = timers.at(-1);
  if (!replayExpiry || replayExpiry.delay !== 10000) {
    throw new Error('natural completion did not preserve the replay window');
  }
  replayExpiry.callback();
  assertRevoked(
    ['blob:first', 'blob:second', 'blob:error', 'blob:rejected', 'blob:ended'],
    'replay expiry did not release the completed URL'
  );

  app._playAudio('https://example.test/audio.mp3');
  app.stopAudioPlayback();
  assertRevoked(
    ['blob:first', 'blob:second', 'blob:error', 'blob:rejected', 'blob:ended'],
    'non-blob audio URL was passed to revokeObjectURL'
  );
})().catch(error => {
  console.error(error);
  process.exit(1);
});
"""
    subprocess.run(["node", "-e", script], cwd=ROOT, check=True)
