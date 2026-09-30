/** Browser-owned, bounded interruption audio. Also copied into Companion source. */
(function (global) {
  const modules = new WeakMap();
  function wav(chunks, sampleRate) {
    const count = chunks.reduce((sum, chunk) => sum + chunk.length, 0);
    const input = new Float32Array(count);
    let offset = 0;
    for (const chunk of chunks) { input.set(chunk, offset); offset += chunk.length; }
    const rate = Math.min(16000, sampleRate);
    const length = Math.floor(count * rate / sampleRate);
    const bytes = new ArrayBuffer(44 + length * 2), view = new DataView(bytes);
    const text = (at, value) => { for (let i = 0; i < value.length; i++) view.setUint8(at + i, value.charCodeAt(i)); };
    text(0, 'RIFF'); view.setUint32(4, bytes.byteLength - 8, true);
    text(8, 'WAVE'); text(12, 'fmt '); view.setUint32(16, 16, true);
    view.setUint16(20, 1, true); view.setUint16(22, 1, true);
    view.setUint32(24, rate, true); view.setUint32(28, rate * 2, true);
    view.setUint16(32, 2, true); view.setUint16(34, 16, true);
    text(36, 'data'); view.setUint32(40, length * 2, true);
    // Average each downsampling interval instead of just dropping samples.
    for (let i = 0; i < length; i++) {
      const start = Math.floor(i * sampleRate / rate);
      const end = Math.max(start + 1, Math.floor((i + 1) * sampleRate / rate));
      let value = 0;
      for (let j = start; j < end; j++) value += input[j] / (end - start);
      value = Math.max(-1, Math.min(1, value));
      view.setInt16(44 + i * 2, value < 0 ? value * 32768 : value * 32767, true);
    }
    return new Blob([bytes], {type: 'audio/wav'});
  }

  class TalkCapture {
    static async create(context, input, url, callbacks) {
      if (!context.audioWorklet || !global.AudioWorkletNode) throw new Error('Speech interruption needs AudioWorklet in this browser.');
      if (!modules.has(context)) {
        const loading = context.audioWorklet.addModule(url);
        modules.set(context, loading);
        loading.catch(() => modules.delete(context));
      }
      let timeout;
      try {
        await Promise.race([modules.get(context), new Promise((_, reject) => {
          timeout = setTimeout(() => reject(new Error('The interruption detector did not load. Use the Interrupt button.')), 8000);
        })]);
      } finally { clearTimeout(timeout); }
      const node = new global.AudioWorkletNode(context, 'jarvis-talk-capture', {
        numberOfInputs: 2, numberOfOutputs: 1, outputChannelCount: [1],
      });
      return new TalkCapture(context, input, node, callbacks);
    }

    constructor(context, input, node, callbacks) {
      Object.assign(this, {context, input, node, callbacks});
      this.token = 0;
      this.closed = false;
      this.chunks = [];
      this.samples = 0;
      input.connect(node, 0, 0);
      node.connect(context.destination); // processor outputs silence
      node.onprocessorerror = () => {
        if (!this.closed) this.callbacks.error(new Error('The interruption detector stopped. Resume Talk to retry.'));
      };
      node.port.onmessage = ({data}) => {
        if (this.closed || data.token !== this.token) return;
        if (data.type === 'speech-start') this.callbacks.start();
        else if (data.type === 'samples') {
          this.samples += data.samples.length;
          if (this.samples > this.context.sampleRate * 46 || this.samples * 4 > 36 * 1024 * 1024) {
            this.disarm(); this.callbacks.error(new Error('The interruption recording exceeded its limit.')); return;
          }
          this.chunks.push(data.samples);
        } else if (data.type === 'speech-end') {
          const chunks = this.chunks;
          this.disarm();
          try { this.callbacks.end(wav(chunks, this.context.sampleRate)); }
          catch (error) { this.callbacks.error(error); }
        }
      };
    }

    arm(source) {
      this.disarm();
      this.source = source;
      source.connect(this.node, 0, 1);
      this.node.port.postMessage({type: 'arm', token: ++this.token});
    }

    releaseReference(source) {
      if (this.source !== source) return;
      try { source.disconnect(this.node); } catch (_) { /* source may already be disconnected */ }
      this.source = null;
    }

    disarm() {
      ++this.token;
      this.node.port.postMessage({type: 'disarm'});
      if (this.source) this.releaseReference(this.source);
      this.chunks = [];
      this.samples = 0;
    }

    close() {
      if (this.closed) return;
      this.closed = true;
      this.disarm();
      this.node.port.onmessage = null;
      this.node.onprocessorerror = null;
      this.node.port.close();
      this.input.disconnect(this.node);
      this.node.disconnect();
    }
  }
  global.JarvisTalkCapture = TalkCapture;
})(globalThis);
