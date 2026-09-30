/** Local microphone pre-roll and playback-reference rejection; no speech recognition. */
class JarvisTalkCaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.frameSize = Math.round(sampleRate * 0.02);
    this.mic = new Float32Array(this.frameSize);
    this.reference = new Float32Array(this.frameSize);
    this.position = 0;
    this.clock = 0;
    this.port.onmessage = ({data}) => {
      if (data.type === 'arm') {
        this.token = data.token;
        this.armed = true;
        this.recording = false;
        this.startedAt = this.clock;
        this.attackAt = null;
        this.voicedMs = 0;
        this.lastVoiceAt = this.clock;
        this.noiseFloor = 0.003;
        this.history = [];
        this.micEnvelope = [];
        this.referenceEnvelope = [];
        this.position = 0;
      } else if (data.type === 'disarm') {
        this.armed = false;
        this.recording = false;
        this.history = [];
        this.micEnvelope = [];
        this.referenceEnvelope = [];
      }
    };
  }

  _envelope(samples) {
    const result = [];
    const width = Math.max(1, Math.round(sampleRate / 1000));
    for (let start = 0; start < samples.length; start += width) {
      let energy = 0;
      const end = Math.min(samples.length, start + width);
      for (let i = start; i < end; i++) energy += samples[i] * samples[i];
      result.push(Math.sqrt(energy / (end - start)));
    }
    return result;
  }

  _echo() {
    // Correlate short energy envelopes across possible acoustic delays. This
    // supplements browser AEC; it is not a promise of perfect echo cancellation.
    const width = 100;
    const mic = this.micEnvelope;
    const reference = this.referenceEnvelope;
    if (mic.length < width) return false;
    const start = mic.length - width;
    let mean = 0;
    for (let i = start; i < mic.length; i++) mean += mic[i] / width;
    let energy = 0;
    for (let i = start; i < mic.length; i++) energy += (mic[i] - mean) ** 2;
    if (energy < 1e-9) return false;
    for (let delay = 0; delay <= Math.min(320, reference.length - width); delay += 2) {
      const refStart = reference.length - width - delay;
      let refMean = 0;
      for (let i = 0; i < width; i++) refMean += reference[refStart + i] / width;
      if (refMean < 0.002) continue;
      let refEnergy = 0, cross = 0;
      for (let i = 0; i < width; i++) {
        const r = reference[refStart + i] - refMean;
        refEnergy += r * r;
        cross += (mic[start + i] - mean) * r;
      }
      if (refEnergy > 1e-9 && cross / Math.sqrt(energy * refEnergy) >= 0.82) return true;
    }
    return false;
  }

  _frame() {
    this.clock += 20;
    if (!this.armed) return;
    const envelope = this._envelope(this.mic);
    this.micEnvelope.push(...envelope);
    this.referenceEnvelope.push(...this._envelope(this.reference));
    if (this.micEnvelope.length > 440) {
      this.micEnvelope.splice(0, this.micEnvelope.length - 440);
      this.referenceEnvelope.splice(0, this.referenceEnvelope.length - 440);
    }
    let energy = 0;
    for (const sample of this.mic) energy += sample * sample;
    const rms = Math.sqrt(energy / this.mic.length);
    const echo = this._echo();
    const threshold = Math.max(0.012, this.noiseFloor * 3.5);
    const voice = rms >= threshold && !echo;
    if (!voice && !echo) this.noiseFloor = 0.98 * this.noiseFloor + 0.02 * Math.min(rms, 0.01);
    const samples = echo ? new Float32Array(this.frameSize) : this.mic.slice();

    if (!this.recording) {
      this.history.push(samples);
      if (this.history.length > 40) this.history.shift(); // 800 ms, including startup/attack
      if (this.clock - this.startedAt < 250) return;
      if (voice) {
        this.attackAt ??= this.clock;
        this.voicedMs += 20;
        this.lastVoiceAt = this.clock;
      } else if (this.clock - this.lastVoiceAt > 120) {
        this.attackAt = null;
        this.voicedMs = 0;
      }
      if (this.attackAt === null || this.clock - this.attackAt < 280 || this.voicedMs < 200) return;
      this.recording = true;
      this.recordingAt = this.clock;
      this.port.postMessage({type: 'speech-start', token: this.token});
      for (const frame of this.history) this._send(frame);
      this.history = [];
    } else {
      this._send(samples);
      if (voice) this.lastVoiceAt = this.clock;
      if (this.clock - this.lastVoiceAt >= 1200 || this.clock - this.recordingAt >= 45000) {
        this.armed = false;
        this.recording = false;
        this.port.postMessage({type: 'speech-end', token: this.token});
      }
    }
  }

  _send(samples) {
    this.port.postMessage({type: 'samples', token: this.token, samples}, [samples.buffer]);
  }

  process(inputs, outputs) {
    // The output is deliberately silent; microphone audio is never monitored
    // through the speakers. Input 1 observes the separate playback source.
    for (const output of outputs) for (const channel of output) channel.fill(0);
    const microphone = inputs[0] || [], reference = inputs[1] || [];
    const length = outputs[0]?.[0]?.length || microphone[0]?.length || 128;
    for (let i = 0; i < length; i++) {
      let mic = 0, ref = 0;
      for (const channel of microphone) mic += (channel[i] || 0) / microphone.length;
      for (const channel of reference) ref += (channel[i] || 0) / reference.length;
      this.mic[this.position] = mic;
      this.reference[this.position] = ref;
      if (++this.position === this.frameSize) { this._frame(); this.position = 0; }
    }
    return true;
  }
}

registerProcessor('jarvis-talk-capture', JarvisTalkCaptureProcessor);
