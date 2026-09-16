/** Audio bytes are transient structured-clone messages, never session storage. */
export class TalkPort {
  constructor(getPort) { this.getPort = getPort; this.pending = new Map(); this.sequence = 0; }

  request(sessionId, action, payload = {}, signal) {
    const port = this.getPort();
    if (!port || signal?.aborted) return Promise.reject(new Error('Talk disconnected.'));
    const id = String(++this.sequence);
    if (['release', 'abort'].includes(action)) {
      try { port.postMessage({type: 'talk:request', sessionId, id, action, payload}); return Promise.resolve(); }
      catch { return Promise.reject(new Error('Talk disconnected.')); }
    }
    return new Promise((resolve, reject) => {
      const finish = (error, value) => {
        clearTimeout(timer);
        signal?.removeEventListener('abort', abort);
        this.pending.delete(id);
        if (error) reject(error); else resolve(value);
      };
      const abort = () => {
        void this.request(sessionId, 'abort', {id}).catch(() => {});
        finish(new Error('Speech request stopped.'));
      };
      const timer = setTimeout(() => {
        void this.request(sessionId, 'abort', {id}).catch(() => {});
        finish(new Error('Speech request timed out. Resume to try again.'));
      }, 95000);
      this.pending.set(id, {sessionId, finish});
      signal?.addEventListener('abort', abort, {once: true});
      try { port.postMessage({type: 'talk:request', sessionId, id, action, payload}); }
      catch { finish(new Error('Talk disconnected.')); }
    });
  }

  receive(message) {
    if (message?.type !== 'talk:reply') return;
    const pending = this.pending.get(message.id);
    if (pending?.sessionId === message.sessionId) pending.finish(message.ok ? null : new Error(message.error), message.value);
  }

  disconnect() {
    for (const pending of [...this.pending.values()]) pending.finish(new Error('Talk disconnected.'));
  }
}
