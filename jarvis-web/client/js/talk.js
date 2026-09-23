/** Hands-free turns through Jarvis's ordinary STT, chat and TTS paths. */
class TalkActivityDetector {
  constructor(startedAt, { silenceMs = 1200, maxMs = 45000, idleMs = 30000 } = {}) {
    Object.assign(this, { startedAt, silenceMs, maxMs, idleMs });
    this.attackAt = null;
    this.lastVoiceAt = null;
    this.heardSpeech = false;
    this.noiseFloor = 0.003;
  }

  update(rms, now) {
    const threshold = Math.max(0.012, Math.min(this.noiseFloor * 3, 0.04));
    if (rms >= threshold) {
      this.attackAt ??= now;
      if (now - this.attackAt >= 250) this.heardSpeech = true;
      this.lastVoiceAt = now;
    } else {
      this.attackAt = null;
      this.noiseFloor = this.noiseFloor * 0.98 + rms * 0.02;
    }
    if (this.heardSpeech && (now - this.lastVoiceAt >= this.silenceMs || now - this.startedAt >= this.maxMs)) return 'submit';
    if (!this.heardSpeech && now - this.startedAt >= this.idleMs) return 'idle';
    return null;
  }
}

class TalkController {
  constructor({ app, chat, socket }) {
    Object.assign(this, { app, chat, socket });
    this.button = document.getElementById('talkBtn');
    this.panel = document.getElementById('talkPanel');
    this.status = document.getElementById('talkStatus');
    this.transcript = document.getElementById('talkTranscript');
    this.pauseButton = document.getElementById('talkPause');
    this.interruptButton = document.getElementById('talkInterrupt');
    this.endButton = document.getElementById('talkEnd');
    this.ownedRequests = new Set();
    this.session = null;
    this.button?.addEventListener('click', () => this.active ? this.end() : this.start());
    this.pauseButton?.addEventListener('click', () => this.session?.paused ? this.resume() : this.pause());
    this.interruptButton?.addEventListener('click', () => this.interrupt());
    this.endButton?.addEventListener('click', () => this.end());
    document.addEventListener('keydown', event => {
      if (event.code === 'Escape' && this.active) { event.preventDefault(); this.end(); }
    });
    document.addEventListener('visibilitychange', () => {
      if (document.hidden && this.active) this.end('Talk ended because this page is hidden. Any submitted task can finish in chat.', { cancel: false });
    });
    window.addEventListener('pagehide', () => this.end('', { cancel: false }));
    socket.on('connectionChange', data => {
      if (!data.connected && this.active) this.end('Talk ended on disconnect. Reconnect to recover your task in chat.', { cancel: false });
    });
    socket.on('modeChanged', () => this.end('Talk ended because the mode changed.'));
    socket.on('conversationLoaded', () => this.end('Talk ended because a conversation was loaded.', { cancel: false }));
    socket.on('conversationCreated', data => {
      const s = this.session;
      if (s && s.conversationId == null && s.turn) s.conversationId = data.conversation_id;
      else if (s && s.conversationId !== data.conversation_id) this.end('Talk ended because the conversation changed.', { cancel: false });
    });
    socket.on('response', data => { void this._response(data); });
    socket.on('runState', data => this._runState(data));
    for (const event of ['error', 'rejected', 'cancelled']) {
      socket.on(event, data => {
        const s = this.session;
        if (!s?.turn || data.message_id !== s.turn.id) return;
        if (event === 'rejected') {
          this.end(data.error || 'The spoken message was not accepted. It is available in the draft.', { cancel: false });
        } else {
          s.turn.answerFinished = true;
          if (!s.interrupting) this.pause(data.error || 'The task stopped. Resume Talk when ready.');
        }
      });
    }
    this._render();
  }

  get active() { return this.session !== null; }
  ownsResponse(data) { return Boolean(data?.message_id && this.ownedRequests.has(data.message_id)); }

  _current(s, generation = s?.generation) {
    return this.session === s && s.generation === generation && this.socket.connected
      && s.mode === this.socket.mode && s.conversationId === (this.socket.conversationId || null)
      && !document.hidden;
  }

  _render(message) {
    const s = this.session;
    const labels = {
      preparing: 'Preparing microphone…', listening: 'Listening — speak, then pause',
      transcribing: 'Transcribing — microphone off', waiting: 'Jarvis is working — microphone off',
      speaking: 'Jarvis is speaking — microphone off', stopping: 'Stopping this task…',
      paused: 'Talk paused — microphone off', settling: 'Finishing this turn…'
    };
    if (this.panel) this.panel.hidden = !s;
    if (this.status) this.status.textContent = message || (s ? labels[s.phase] : 'Talk ended');
    if (this.button) {
      this.button.setAttribute('aria-pressed', String(Boolean(s)));
      this.button.classList.toggle('active', Boolean(s));
      this.button.title = s ? 'End Talk (Esc)' : 'Start hands-free Talk — speech is sent automatically';
      this.button.setAttribute('aria-label', s ? 'End hands-free Talk' : 'Start hands-free Talk');
    }
    if (this.pauseButton) {
      this.pauseButton.hidden = !s;
      this.pauseButton.textContent = s?.paused ? 'Resume' : 'Pause';
      this.pauseButton.disabled = s?.phase === 'stopping';
    }
    if (this.interruptButton) this.interruptButton.hidden = !s || !['speaking', 'waiting', 'transcribing'].includes(s.phase);
    if (this.endButton) this.endButton.hidden = !s;
    if (this.panel) this.panel.dataset.state = s?.phase || 'ended';
    this.chat._talkActive = Boolean(s);
    this.chat.updateSendButton();
  }

  async start() {
    if (this.active) return;
    if (!this.socket.connected || this.chat.isProcessing || this.chat._conversationLoadPending) {
      Utils.toast('Connect to Jarvis and wait for the current task before starting Talk.', 'info'); return;
    }
    if (this.chat._voiceSession || this.chat.inputField.value.trim() || this.chat.attachedDocuments.length
        || this.chat.attachedImages.length || this.chat.pendingImageFiles?.length || this.chat._imageUpload
        || this.chat._attachmentSend || this.chat.enhanceBtn?.classList.contains('enhancing')) {
      Utils.toast('Send or clear your draft and finish dictation or attachments before starting Talk.', 'info'); return;
    }
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder || !(window.AudioContext || window.webkitAudioContext)) {
      Utils.toast('Talk requires microphone recording and Web Audio in a browser on HTTPS or localhost.', 'warning', 6000); return;
    }
    this.app._cancelStatusTTS();
    this.app._talkAudioEpoch = (this.app._talkAudioEpoch || 0) + 1;
    this.app.stopAudioPlayback();
    const s = this.session = {
      mode: this.socket.mode, conversationId: this.socket.conversationId || null,
      phase: 'preparing', paused: false, generation: 0, turn: null
    };
    s.composerState = [this.chat.micBtn, this.chat.uploadBtn, this.chat.enhanceBtn,
      document.getElementById('convertBtn')].filter(Boolean).map(element => [element, element.disabled]);
    s.composerState.forEach(([element]) => { element.disabled = true; });
    s.draftReadOnly = this.chat.inputField.readOnly;
    this.chat.inputField.readOnly = true;
    if (this.transcript) this.transcript.textContent = '';
    this._render();
    void this.app._warmTTS?.(s.mode);
    await this._openMedia(s);
  }

  async _openMedia(s) {
    const generation = s.generation;
    try {
      // Create/resume during the Start/Resume gesture to unlock browser audio.
      const Context = window.AudioContext || window.webkitAudioContext;
      s.context = new Context();
      await s.context.resume();
      if (!this._current(s, generation)) return;
      const stream = await navigator.mediaDevices.getUserMedia({audio: {
        echoCancellation: true, noiseSuppression: true, autoGainControl: true
      }});
      if (!this._current(s, generation)) { stream.getTracks().forEach(track => track.stop()); return; }
      s.stream = stream;
      for (const track of stream.getTracks()) track.onended = () => {
        if (this._current(s)) this.pause('The microphone disconnected. Reconnect it, then Resume.');
      };
      s.input = s.context.createMediaStreamSource(stream);
      s.analyser = s.context.createAnalyser();
      s.analyser.fftSize = 2048;
      s.input.connect(s.analyser);
      if (s.turn && !s.turn.settled) {
        this._mute(s); s.phase = 'waiting'; this._render();
      } else {
        s.turn = null;
        this._listen(s);
      }
    } catch (error) {
      if (!this._current(s, generation)) return;
      this.pause(error.name === 'NotAllowedError'
        ? 'Microphone access was denied. Allow it in your browser, then Resume.'
        : `Talk could not start: ${error.message || 'microphone unavailable'}`);
    }
  }

  _mute(s) { s.stream?.getAudioTracks().forEach(track => { track.enabled = false; }); }

  _listen(s) {
    if (!this._current(s) || s.paused || s.turn || this.chat.isProcessing) return;
    try {
      s.phase = 'listening';
      s.stream.getAudioTracks().forEach(track => { track.enabled = true; });
      const preferred = ['audio/webm;codecs=opus', 'audio/mp4', 'audio/ogg;codecs=opus', 'audio/webm'];
      const mimeType = preferred.find(type => MediaRecorder.isTypeSupported(type));
      const recorder = s.recorder = new MediaRecorder(s.stream, mimeType ? { mimeType } : {});
      const generation = s.generation;
      const chunks = [];
      let bytes = 0;
      const detector = new TalkActivityDetector(performance.now());
      const samples = new Float32Array(s.analyser.fftSize);
      recorder.ondataavailable = event => {
        if (!this._current(s, generation) || !event.data.size) return;
        chunks.push(event.data); bytes += event.data.size;
        if (bytes > 10 * 1024 * 1024) this.pause('The recording grew too large. Resume and use a shorter question.');
      };
      recorder.onerror = () => { if (this._current(s, generation)) this.pause('Recording failed. Resume to try again.'); };
      recorder.onstop = () => {
        if (!this._current(s, generation) || s.recorder !== recorder || !s.submitRecording) return;
        s.recorder = null;
        void this._transcribe(s, new Blob(chunks, {type: recorder.mimeType || mimeType}), generation);
      };
      s.submitRecording = false;
      recorder.start(100);
      s.poll = setInterval(() => {
        if (!this._current(s, generation)) return;
        s.analyser.getFloatTimeDomainData(samples);
        const rms = Math.sqrt(samples.reduce((sum, value) => sum + value * value, 0) / samples.length);
        const action = detector.update(rms, performance.now());
        if (action === 'idle') this.pause('No speech heard. Resume Talk when ready.');
        if (action === 'submit') {
          clearInterval(s.poll); s.poll = null;
          s.submitRecording = true;
          s.phase = 'transcribing';
          recorder.stop();
          this._mute(s);
          this._render();
        }
      }, 50);
      this._render();
    } catch (error) {
      this.pause(`Recording could not start: ${error.message}`);
    }
  }

  async _request(s, url, options, generation) {
    const controller = s.request = new AbortController();
    const timer = setTimeout(() => controller.abort(), 90000);
    try {
      const response = await Utils.auth.fetch(url, {...options, signal: controller.signal});
      if (!this._current(s, generation)) throw new DOMException('Talk ended', 'AbortError');
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || `Speech service returned HTTP ${response.status}`);
      }
      // Read the body within the same abort/deadline boundary.
      return options.responseType === 'json' ? await response.json() : await response.arrayBuffer();
    } finally {
      clearTimeout(timer);
      if (s.request === controller) s.request = null;
    }
  }

  async _transcribe(s, blob, generation) {
    try {
      if (!blob.size) throw new Error('No audio was recorded.');
      const extension = {'audio/mp4': 'mp4', 'audio/ogg': 'ogg', 'audio/wav': 'wav'}[blob.type.split(';')[0]] || 'webm';
      const body = new FormData();
      body.append('audio', blob, `talk.${extension}`); body.append('mode', s.mode);
      const result = await this._request(s, '/api/stt', {method: 'POST', body, responseType: 'json'}, generation);
      if (!this._current(s, generation) || s.paused) return;
      const text = typeof result.text === 'string' ? result.text.trim() : '';
      if (!result.ok || !text) throw new Error(result.error || 'No speech detected.');
      if (this.transcript) this.transcript.textContent = `You said: ${text}`;
      if (/^(?:end talk|stop listening|goodbye)[.!?]*$/i.test(text)) { this.end(); return; }
      const id = this.chat.sendTalkMessage(text);
      if (!id) throw new Error('The spoken message could not be sent. Resume when Jarvis is ready.');
      this.ownedRequests.add(id);
      if (this.ownedRequests.size > 200) this.ownedRequests.delete(this.ownedRequests.values().next().value);
      s.turn = {id, settled: false, responseReceived: false, answerFinished: false};
      s.phase = 'waiting'; this._render();
    } catch (error) {
      if (this._current(s, generation)) this.pause(error.name === 'AbortError'
        ? 'Speech transcription timed out. Resume to try again.' : error.message);
    }
  }

  _runState(data) {
    const s = this.session;
    if (s && data.conversation_id === s.conversationId && data.status === 'running'
        && data.message_id !== s.turn?.id && !s.paused) {
      this.pause('Another task started in this conversation. Wait for it to finish, then Resume.');
    }
    if (!s?.turn || data.message_id !== s.turn.id || data.conversation_id !== s.conversationId) return;
    if (['running', 'stopping'].includes(data.status)) return;
    s.turn.settled = true;
    if (data.status !== 'completed') {
      s.turn.answerFinished = true;
      if (!s.interrupting) this.pause(data.error || 'The task did not complete. Resume when ready.');
    }
    this._advance(s);
  }

  async _response(data) {
    const s = this.session;
    if (!s?.turn || data.message_id !== s.turn.id || s.turn.responseReceived) return;
    s.turn.responseReceived = true;
    if (s.paused || s.interrupting || s.turn.silent || data.cancelled || data.ok === false) {
      s.turn.answerFinished = true;
      if (!s.paused && !s.interrupting && !s.turn.silent) this.pause('The task did not complete. Check the reply, then Resume.');
      this._advance(s); return;
    }
    const generation = s.generation;
    try {
      s.phase = 'speaking'; this._render();
      if (data.audio_url) {
        const url = new URL(data.audio_url, window.location.href);
        if (url.origin !== window.location.origin) throw new Error('The answer audio is not on this Jarvis server.');
        await this._play(s, await this._request(s, url.href, {method: 'GET'}, generation), generation);
      } else {
        const text = typeof data.speech === 'string' ? data.speech.trim() : '';
        if (!text) throw new Error('This reply has no spoken text. Read it in chat, then Resume.');
        if (text.length > 12000) throw new Error('This reply is too long for Talk. Read it in chat, then Resume.');
        let remaining = text;
        while (remaining) {
          if (!this._current(s, generation) || s.paused) return;
          let end = Math.min(remaining.length, 950);
          if (end < remaining.length) {
            const boundary = remaining.lastIndexOf(' ', end);
            if (boundary > 400) end = boundary;
          }
          const chunk = remaining.slice(0, end);
          remaining = remaining.slice(end).trimStart();
          const buffer = await this._request(s, '/api/tts', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({text: chunk, mode: s.mode, purpose: 'final', message_id: data.message_id})
          }, generation);
          await this._play(s, buffer, generation);
        }
      }
      if (!this._current(s, generation)) return;
      s.turn.answerFinished = true;
      this._advance(s);
    } catch (error) {
      if (this._current(s, generation)) {
        s.turn.answerFinished = true;
        this.pause(error.name === 'AbortError' ? 'Speech playback timed out. The reply is saved in chat.' : `Could not speak the reply: ${error.message}`);
      }
    }
  }

  async _play(s, bytes, generation) {
    const buffer = await s.context.decodeAudioData(bytes);
    if (!this._current(s, generation) || s.paused) return;
    if (s.context.state !== 'running') throw new Error('Browser audio is suspended. Press Resume to enable it.');
    await new Promise((resolve, reject) => {
      const source = s.playback = s.context.createBufferSource();
      source.buffer = buffer;
      source.connect(s.context.destination);
      source.onended = () => {
        source.disconnect();
        if (s.playback === source) s.playback = null;
        resolve();
      };
      try { source.start(); } catch (error) { source.disconnect(); s.playback = null; reject(error); }
    });
  }

  _advance(s) {
    if (!this._current(s) || s.paused || !s.turn?.settled || !s.turn.answerFinished) return;
    // Resume may still be awaiting microphone permission when the task ends.
    // _openMedia will advance after acquiring its stream; never arm early.
    if (!s.stream || !s.context || s.phase === 'preparing') return;
    s.turn = null; s.interrupting = false;
    // Allow speaker echo to decay before capturing the next turn.
    s.phase = 'settling'; this._render();
    s.next = setTimeout(() => { s.next = null; if (this._current(s)) this._listen(s); }, 350);
  }

  _dispose(s) {
    s.generation += 1;
    clearInterval(s.poll); clearTimeout(s.next);
    s.poll = null; s.next = null;
    s.request?.abort(); s.request = null;
    if (s.recorder) {
      s.recorder.onstop = null; s.recorder.ondataavailable = null; s.recorder.onerror = null;
      if (s.recorder.state !== 'inactive') s.recorder.stop();
      s.recorder = null;
    }
    if (s.playback) { s.playback.stop(); s.playback = null; }
    s.stream?.getTracks().forEach(track => { track.onended = null; track.stop(); });
    s.stream = null;
    s.input?.disconnect(); s.analyser?.disconnect();
    s.input = null; s.analyser = null;
    void s.context?.close().catch(() => {}); s.context = null;
  }

  pause(message = 'Talk paused — microphone off') {
    const s = this.session;
    if (!s) return;
    this._dispose(s);
    s.paused = true; s.phase = 'paused';
    if (s.turn) s.turn.silent = true;
    if (s.turn?.responseReceived) s.turn.answerFinished = true;
    this._render(message);
  }

  async resume() {
    const s = this.session;
    if (!s?.paused || !this._current(s)) return;
    if (this.chat.isProcessing && (!s.turn || s.turn.settled)) {
      Utils.toast('Wait for the current task to finish before resuming Talk.', 'info'); return;
    }
    s.paused = false; s.phase = 'preparing';
    this._render();
    void this.app._warmTTS?.(s.mode);
    await this._openMedia(s);
  }

  interrupt() {
    const s = this.session;
    if (!s || s.paused) return;
    if (s.turn && !s.turn.settled) {
      s.generation += 1;
      s.interrupting = true;
      s.turn.answerFinished = true;
      s.request?.abort();
      if (s.playback) { s.playback.stop(); s.playback = null; }
      s.phase = 'stopping'; this._render();
      this.socket.cancel(s.conversationId, s.turn.id);
      return;
    }
    // Reopening from this click also re-enables audio after browser suspension.
    s.turn = null;
    this.pause();
    void this.resume();
  }

  end(message = '', { cancel = true } = {}) {
    const s = this.session;
    if (!s) return;
    this.session = null;
    if (cancel && s.turn && !s.turn.settled && this.socket.connected) this.socket.cancel(s.conversationId, s.turn.id);
    this._dispose(s);
    s.composerState.forEach(([element, disabled]) => { element.disabled = disabled; });
    this.chat.inputField.readOnly = s.draftReadOnly;
    this._render(message);
    if (message) Utils.toast(message, 'info', 5000);
    if (!document.hidden) this.button?.focus();
  }
}

window.TalkActivityDetector = TalkActivityDetector;
window.TalkController = TalkController;
