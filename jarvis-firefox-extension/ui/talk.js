/** Hands-free turns through Jarvis's ordinary STT, chat and TTS paths. */
export class TalkActivityDetector {
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

export class TalkController {
  constructor({getState, rpc, notify, render, hasDraft, getMicrophone = constraints => navigator.mediaDevices.getUserMedia(constraints)}) {
    Object.assign(this, {getState, rpc, notify, render, hasDraft, getMicrophone});
    this.session = null;
  }

  get active() { return this.session !== null; }

  _current(s, generation = s?.generation) {
    const state = this.getState();
    return this.session === s && s.generation === generation && !document.hidden &&
      s.mode === state?.mode && s.serverUrl === state?.settings?.serverUrl &&
      s.conversationId === (state?.conversationId || null) &&
      !['disconnected', 'error', 'auth_required', 'unconfigured'].includes(state?.connection?.status);
  }

  _render(message) {
    const s = this.session;
    if (s && message) s.message = message;
    else if (s) s.message = '';
    this.render(s);
  }

  update(state) {
    const s = this.session;
    if (!s) return;
    if (s.conversationId == null && s.turn && state.run?.messageId === s.turn.id) s.conversationId = state.conversationId || null;
    if (!this._current(s) || ['recovering', 'connecting'].includes(state.connection.status) && !s.sending) {
      this.end('Talk ended because the connection or conversation changed.', {cancel: false});
    }
  }

  event(event, data) {
    if (event === 'chat:run') this._runState(data);
    else if (event === 'chat:response') void this._response(data);
    else if (this.session?.turn?.id === data.message_id) {
      if (event === 'chat:rejected' || event === 'chat:error' && data.admitted === false) {
        this.end(data.error || 'The spoken message was not accepted. Check your draft.', {cancel: false});
      } else {
        const s = this.session;
        s.turn.answerFinished = true;
        if (event === 'chat:cancelled') s.turn.settled = true;
        if (!s.interrupting) this.pause(data.error || 'The task stopped. Resume when ready.');
        this._advance(s);
      }
    }
  }

  async start() {
    if (this.active) return;
    const state = this.getState();
    if (state?.connection?.status !== 'connected' || !state.capabilities?.talk ||
        ['running', 'sending', 'stopping', 'recovering'].includes(state.run?.status) || state.pendingMode) {
      this.notify('Connect to an updated Jarvis Web server and wait for the current task before starting Talk.'); return;
    }
    if (this.hasDraft()) { this.notify('Send or clear your draft and attachments before starting Talk.'); return; }
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder || !window.AudioContext) {
      this.notify('This browser cannot record microphone audio. Open Talk in Firefox on desktop.'); return;
    }
    const s = this.session = {
      id: crypto.randomUUID(), mode: state.mode, serverUrl: state.settings.serverUrl,
      conversationId: state.conversationId || null, phase: 'preparing', paused: false, generation: 0, turn: null,
    };
    this._render();
    const generation = s.generation;
    // Try to unlock playback in the click, but never wait for autoplay before
    // requesting capture: Firefox may unlock audio only after microphone access.
    try {
      s.context = new window.AudioContext();
      void s.context.resume().catch(() => {});
      await this.rpc(s.id, 'claim');
      if (this._current(s, generation)) await this._openMedia(s);
    } catch (error) {
      if (this.session === s) this.end(error.message, {cancel: false});
    }
  }

  _waitForMedia(s, promise, timeout, message, discardLate) {
    return new Promise((resolve, reject) => {
      let finished = false;
      const finish = (error, value) => {
        if (finished) return;
        finished = true;
        clearTimeout(timer);
        if (s.cancelMediaWait === cancel) s.cancelMediaWait = null;
        if (error) reject(error); else resolve(value);
      };
      const cancel = () => finish(new DOMException('Talk stopped', 'AbortError'));
      const timer = setTimeout(() => finish(new Error(message)), timeout);
      s.cancelMediaWait = cancel;
      Promise.resolve(promise).then(value => {
        if (finished) discardLate?.(value);
        else finish(null, value);
      }, error => finish(error));
    });
  }

  async _openMedia(s) {
    const generation = s.generation;
    try {
      if (!s.context) s.context = new window.AudioContext();
      void s.context.resume().catch(() => {});
      if (!this._current(s, generation)) return;
      s.mediaAbort = new AbortController();
      const capture = this.getMicrophone({audio: {
        echoCancellation: true, noiseSuppression: true, autoGainControl: true
      }}, {signal: s.mediaAbort.signal, onClosed: () => {
        if (this._current(s, generation)) this.pause('Microphone setup was closed. Reopen it from Settings, then Resume.');
      }});
      const stream = await this._waitForMedia(s, capture, 30000,
        'Firefox did not open the microphone. Open Microphone setup, choose Allow, then Resume.',
        late => late.getTracks().forEach(track => track.stop()));
      if (!this._current(s, generation)) { stream.getTracks().forEach(track => track.stop()); return; }
      s.stream = stream;
      s.permissionDenied = false;
      await this._waitForMedia(s, s.context.resume(), 8000,
        'Firefox did not start audio playback. Resume to retry, or use Talk in the full extension tab.');
      if (!this._current(s, generation)) return;
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
      s.permissionDenied = error.name === 'NotAllowedError';
      console.warn('[Jarvis Talk] Microphone/audio startup:', error.name, error.message);
      this.pause(s.permissionDenied ? 'Open Microphone setup, choose Allow microphone, and keep that tab open. Return here and Resume.'
        : `Talk could not start: ${error.message || 'microphone unavailable'}`);
    }
  }

  _mute(s) { s.stream?.getAudioTracks().forEach(track => { track.enabled = false; }); }

  _listen(s) {
    if (!this._current(s) || s.paused || s.turn || ['running', 'sending', 'stopping', 'recovering'].includes(this.getState().run?.status)) return;
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

  async _request(s, action, payload, generation) {
    const controller = s.request = new AbortController();
    try {
      const value = await this.rpc(s.id, action, payload, controller.signal);
      if (!this._current(s, generation)) throw new DOMException('Talk ended', 'AbortError');
      return value;
    } finally { if (s.request === controller) s.request = null; }
  }

  async _transcribe(s, blob, generation) {
    try {
      const bytes = await blob.arrayBuffer();
      if (!this._current(s, generation)) return;
      const result = await this._request(s, 'stt', {bytes, mimeType: blob.type}, generation);
      if (!this._current(s, generation) || s.paused) return;
      const text = typeof result.text === 'string' ? result.text.trim() : '';
      if (!result.ok || !text) throw new Error(result.error || 'No speech detected.');
      s.transcript = text;
      if (/^(?:end talk|stop listening|goodbye)[.!?]*$/i.test(text)) { this.end(); return; }
      // Own the ID before sending: socket events can beat the command reply.
      const id = crypto.randomUUID();
      s.turn = {id, settled: false, responseReceived: false, answerFinished: false};
      s.phase = 'waiting'; s.sending = true; this._render();
      try { await this._request(s, 'send', {text, requestId: id}, generation); }
      finally { s.sending = false; }
    } catch (error) {
      if (this._current(s, generation)) this.pause(error.message || 'Speech transcription failed. Resume to try again.');
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
    if (data.status !== 'completed' && !['denied', 'expired'].includes(s.turn.approvalOutcome)) {
      s.turn.answerFinished = true;
      if (!s.interrupting) this.pause(data.error || 'The task did not complete. Resume when ready.');
    }
    this._advance(s);
  }

  async _response(data) {
    const s = this.session;
    if (!s?.turn || data.message_id !== s.turn.id || s.turn.responseReceived) return;
    s.turn.responseReceived = true;
    s.turn.approvalOutcome = data.approval_outcome?.decision;
    const approvalReply = ['denied', 'expired'].includes(s.turn.approvalOutcome);
    if (s.paused || s.interrupting || s.turn.silent || (data.cancelled && !approvalReply) || data.ok === false) {
      s.turn.answerFinished = true;
      if (!s.paused && !s.interrupting && !s.turn.silent) this.pause('The task stopped. Check the reply, then Resume.');
      this._advance(s); return;
    }
    const generation = s.generation;
    try {
      s.phase = 'speaking'; this._render();
      if (data.audio_url) {
        await this._play(s, await this._request(s, 'audio', {messageId: data.message_id}, generation), generation);
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
          const buffer = await this._request(s, 'tts', {text: chunk, messageId: data.message_id}, generation);
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
    s.cancelMediaWait?.(); s.cancelMediaWait = null;
    s.mediaAbort?.abort(); s.mediaAbort = null;
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
    if (['running', 'sending', 'stopping', 'recovering'].includes(this.getState().run?.status) && (!s.turn || s.turn.settled)) {
      this.notify('Wait for the current task to finish before resuming Talk.'); return;
    }
    s.paused = false; s.phase = 'preparing';
    this._render();
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
      void this.rpc(s.id, 'cancel').catch(error => { if (this.session === s) this.pause(error.message); });
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
    this._dispose(s);
    void this.rpc(s.id, 'release', {cancel}).catch(() => {});
    this._render();
    if (message) this.notify(message);
  }
}
