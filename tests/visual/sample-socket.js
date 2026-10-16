/* Preview-only transport: production UI handlers receive inert sample events. */
(() => {
  try {
    window.sessionStorage.setItem('jarvis.activeConversation', 'demo-research');
  } catch (_) { /* Storage may be disabled in a browser preview. */ }
  window.io = () => {
    const listeners = new Map();
    const deliver = (name, data) => (listeners.get(name) || []).forEach(fn => fn(data));
    const socket = {
      connected: true,
      id: 'sample-browser-session',
      on(name, callback) {
        if (!listeners.has(name)) listeners.set(name, []);
        listeners.get(name).push(callback);
        return socket;
      },
      off(name, callback) {
        listeners.set(name, (listeners.get(name) || []).filter(fn => fn !== callback));
        return socket;
      },
      emit(name, payload, callback) {
        if (name === 'conversation:load') {
          fetch('/api/conversations/demo-research').then(r => r.json()).then(data => {
            deliver('conversation:loaded', data);
          });
        } else if (name === 'logs:subscribe') {
          setTimeout(() => deliver('logs:subscribed', {ok: true}), 0);
        }
        if (typeof callback === 'function') callback({ok: true});
        return socket;
      },
      connect() { return socket; },
      disconnect() { socket.connected = false; return socket; },
    };
    setTimeout(() => {
      deliver('connect');
      deliver('connected', {session_id: socket.id, mode: 'cloud', tools_count: 241,
                            deployment: 'native'});
    }, 100);
    return socket;
  };
})();
