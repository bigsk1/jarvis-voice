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
        signal: AbortSignal.timeout(path === '/api/upload-image' ? 60000 : 15000),
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
  login(password) { return this.request('/api/auth/login', {method: 'POST', body: {password}, authenticated: false}); }
  listConversations() { return this.request('/api/conversations?limit=100&include_archived=false'); }

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
