/** All Jarvis HTTP and Socket.IO details stay in this module. */
export class JarvisTransport {
  constructor({serverUrl, token = '', fetchImpl = (...args) => globalThis.fetch(...args), ioFactory, onUnauthorized = () => {}}) {
    Object.assign(this, {serverUrl, token, fetchImpl, ioFactory, onUnauthorized});
    this.socket = null;
  }

  async request(path, {method = 'GET', body, authenticated = true} = {}) {
    const headers = {};
    if (authenticated && this.token) headers.Authorization = `Bearer ${this.token}`;
    if (body && !(body instanceof FormData)) {
      headers['Content-Type'] = 'application/json';
      body = JSON.stringify(body);
    }
    let response;
    try {
      response = await this.fetchImpl(`${this.serverUrl}${path}`, {
        method, headers, body, credentials: 'omit', redirect: 'error', cache: 'no-store',
        signal: AbortSignal.timeout(path === '/api/upload-image' || path === '/api/upload-text' || path.startsWith('/api/library/capture?') ? 60000 : 15000),
      });
    } catch {
      throw new Error('Could not reach Jarvis. Check the address, certificate, server, and Firefox permission.');
    }
    if (response.status === 401 && authenticated) this.onUnauthorized();
    let data;
    try { data = await response.json(); }
    catch { throw new Error('Jarvis returned an unexpected response. Check that this is the Web server address.'); }
    if (!response.ok || data.ok === false) throw new Error(data.error || `Jarvis request failed (${response.status}).`);
    return data;
  }

  status() { return this.request('/api/status', {authenticated: false}); }
  profile() { return this.request('/api/profile-appearance'); }
  login(password) { return this.request('/api/auth/login', {method: 'POST', body: {password}, authenticated: false}); }
  listConversations() { return this.request('/api/conversations?limit=100&include_archived=false'); }

  async speech(path, {body, signal, audio = false} = {}) {
    const url = new URL(path, this.serverUrl);
    if (url.origin !== this.serverUrl || url.username || url.password || url.search || url.hash ||
        !['/api/stt', '/api/tts'].includes(url.pathname) && !/^\/audio\/[A-Za-z0-9_./-]+$/.test(url.pathname)) {
      throw new Error('The answer audio is not on this Jarvis server.');
    }
    const headers = this.token ? {Authorization: `Bearer ${this.token}`} : {};
    if (body && !(body instanceof FormData)) {
      headers['Content-Type'] = 'application/json';
      body = JSON.stringify(body);
    }
    const response = await this.fetchImpl(url.href, {
      method: body ? 'POST' : 'GET', headers, body, credentials: 'omit', redirect: 'error', cache: 'no-store',
      signal: AbortSignal.any([AbortSignal.timeout(90000), ...(signal ? [signal] : [])]),
    });
    if (response.status === 401) this.onUnauthorized();
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.error || `Speech service returned HTTP ${response.status}`);
    }
    if (!audio) return response.json();
    if (!/^(audio\/|application\/octet-stream)/i.test(response.headers.get('Content-Type') || '')) {
      throw new Error('Jarvis returned an unexpected audio format.');
    }
    // Bound decoded input before it crosses the extension message bridge.
    const reader = response.body.getReader();
    const chunks = [];
    let size = 0;
    try {
      for (;;) {
        const {done, value} = await reader.read();
        if (done) break;
        size += value.byteLength;
        if (size > 32 * 1024 * 1024) throw new Error('The answer audio is too large. Read the reply in chat.');
        chunks.push(value);
      }
    } finally { await reader.cancel().catch(() => {}); }
    const bytes = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
    return bytes.buffer;
  }

  transcribe(bytes, mimeType, mode, signal) {
    if (!(bytes instanceof ArrayBuffer) || !bytes.byteLength || bytes.byteLength > 10 * 1024 * 1024 ||
        !/^audio\/(webm|ogg|mp4|wav)(;codecs=opus)?$/.test(mimeType)) {
      throw new Error('The recording is invalid or too large. Resume and try a shorter question.');
    }
    const form = new FormData();
    form.set('audio', new Blob([bytes], {type: mimeType}), `talk.${mimeType.split(/[\/;]/)[1]}`);
    form.set('mode', mode);
    return this.speech('/api/stt', {body: form, signal});
  }

  synthesize(text, mode, messageId, signal) {
    if (typeof text !== 'string' || !text.trim() || text.length > 950) throw new Error('Invalid speech text.');
    return this.speech('/api/tts', {body: {text, mode, purpose: 'final', message_id: messageId}, signal, audio: true});
  }

  async upload(attachment, mode) {
    if (!/^data:image\/jpeg;base64,[A-Za-z0-9+/=]+$/.test(attachment.previewUrl) ||
        attachment.previewUrl.length > 3000000 || attachment.width > 1024 || attachment.height > 1024) {
      throw new Error('The staged screenshot is invalid. Capture the page again.');
    }
    const bytes = Uint8Array.from(atob(attachment.previewUrl.split(',')[1]), char => char.charCodeAt(0));
    const form = new FormData();
    form.set('image', new Blob([bytes], {type: 'image/jpeg'}), 'screenshot.jpg');
    form.set('mode', mode);
    form.set('include_base64', 'false');
    const result = await this.request('/api/upload-image', {method: 'POST', body: form});
    if (!/^upload_[A-Za-z0-9_-]+\.jpg$/.test(result.filename || '') || result.url !== `/api/uploads/${result.filename}`) {
      throw new Error('Jarvis returned invalid image metadata.');
    }
    return {filename: result.filename, url: result.url};
  }

  async uploadText(page, mode) {
    const markdown = String(page?.markdown || '');
    const bytes = new TextEncoder().encode(markdown);
    if (!markdown.trim() || bytes.length > 100 * 1024) {
      throw new Error('The staged page text is invalid. Capture the page again.');
    }
    if (!/^[0-9a-f-]{36}$/i.test(page.uploadId || '')) {
      throw new Error('The staged page text is invalid. Capture the page again.');
    }
    const form = new FormData();
    form.set('file', new Blob([bytes], {type: 'text/markdown'}), page.filename || 'browser-page.md');
    form.set('upload_id', page.uploadId);
    form.set('mode', mode);
    const result = await this.request('/api/upload-text', {method: 'POST', body: form});
    const attachment = result.attachment;
    if (attachment?.kind !== 'text'
        || !/^stash:\/\/space_web_text_[0-9a-f]{32}\/f_[0-9a-f]{12}$/.test(attachment.stash_ref || '')
        || attachment.filename !== (page.filename || 'browser-page.md')) {
      throw new Error('Jarvis returned invalid text metadata.');
    }
    return {
      kind: 'text',
      stash_ref: attachment.stash_ref,
      filename: attachment.filename,
      upload_id: attachment.upload_id,
    };
  }

  async savePageToLibrary(page, mode) {
    const markdown = String(page?.markdown || '');
    if (!markdown.trim() || new TextEncoder().encode(markdown).length > 100 * 1024 ||
        !['cloud', 'local'].includes(mode)) {
      throw new Error('The staged page text is invalid. Capture the page again.');
    }
    const result = await this.request(`/api/library/capture?mode=${mode}`, {method: 'POST', body: {
      markdown, title: String(page.title || 'Captured page').slice(0, 200),
      url: page.url, captured_at: page.capturedAt,
    }});
    if (!/^[0-9a-f]{64}$/.test(result.source?.source_id || '') || result.source.mode !== mode) {
      throw new Error('Jarvis returned invalid Library source metadata.');
    }
    return result.source;
  }

  open(handlers) {
    this.close();
    this.socket = this.ioFactory(this.serverUrl, {
      autoConnect: false, forceNew: true, transports: ['websocket', 'polling'],
      reconnection: true, reconnectionDelay: 1000, reconnectionDelayMax: 10000,
      timeout: 15000, withCredentials: false,
      auth: callback => callback({token: this.token}),
    });
    for (const [event, handler] of Object.entries(handlers)) this.socket.on(event, handler);
    this.socket.connect();
  }

  emit(event, data) {
    if (!this.socket?.connected) throw new Error('Jarvis disconnected. Reconnect to check the previous request before sending again.');
    // Do not use Socket.IO's offline send buffer for actions that execute work.
    this.socket.emit(event, data);
  }

  close() {
    if (this.socket) { this.socket.removeAllListeners(); this.socket.disconnect(); }
    this.socket = null;
  }
}
