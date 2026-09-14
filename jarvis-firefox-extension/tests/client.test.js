import test from 'node:test';
import assert from 'node:assert/strict';
import {JarvisClient} from '../core/client.js';

const ORIGIN = 'https://jarvis.example';
const ID = '9c892f85-b79a-44c3-9be1-6b66d2f73145';
const NEXT = '9c892f85-b79a-44c3-9be1-6b66d2f73146';
const CAPABILITIES = {features: {auth: false}, extension: {api: 1, socket_auth: true,
  features: {chat: true, images: true, conversations: true, recovery: true, cancel: true}}};
const tick = () => new Promise(resolve => setImmediate(resolve));

function area(initial = {}) {
  const data = structuredClone(initial);
  return {data, get: async key => ({[key]: structuredClone(data[key])}),
    set: async values => Object.assign(data, structuredClone(values))};
}

function harness(options = {}) {
  const storage = options.storage || {local: area(), session: area()};
  const sockets = [], requests = [];
  const permissions = options.permissions || {contains: async () => true};
  const fetchImpl = async (url, init) => {
    requests.push({url, init});
    let body = {ok: true};
    if (url.endsWith('/api/status')) body = options.capabilities || CAPABILITIES;
    if (url.includes('/api/conversations?')) body.conversations = [];
    if (url.endsWith('/api/auth/login')) body.token = 'session-secret';
    if (url.endsWith('/api/upload-image')) {
      if (options.uploadFailure) throw new Error('offline');
      body = {ok: true, filename: 'upload_test.jpg', url: '/api/uploads/upload_test.jpg'};
    }
    return {ok: true, status: 200, json: async () => body};
  };
  const ioFactory = (url, config) => {
    const socket = {url, config, handlers: {}, sent: [], connected: false,
      on(name, fn) { this.handlers[name] = fn; },
      connect() { this.connected = true; },
      emit(name, data) {
        if (name === 'chat:send') assert.equal(storage.session.data.jarvisSession.pendingRequestId, data.request_id);
        this.sent.push({name, data});
      },
      receive(name, data = {}) { this.handlers[name]?.(data); },
      removeAllListeners() { this.handlers = {}; },
      disconnect() { this.connected = false; },
    };
    sockets.push(socket);
    return socket;
  };
  let id = ID;
  const client = new JarvisClient({storage, permissions, fetchImpl, ioFactory, uuid: () => { const next = id; id = NEXT; return next; }});
  return {client, storage, sockets, requests, async start() {
    await client.restore(); await client.configure({serverUrl: ORIGIN}); await client.connect();
    sockets.at(-1)?.receive('connected', {mode: 'cloud'});
    await tick();
  }};
}

test('fresh profile initializes without a saved session', async () => {
  const h = harness(); await h.client.restore();
  assert.equal(h.client.state.connection.status, 'unconfigured');
  assert.equal(h.client.token, '');
});

test('an incompatible server is rejected before login or socket creation', async () => {
  const h = harness({capabilities: {features: {auth: false}}});
  await assert.rejects(h.start(), /server|update|extension/i);
  assert.equal(h.sockets.length, 0);
  assert.equal(h.requests.length, 1);
});

test('authentication lives only in session and is presented through socket auth', async () => {
  const h = harness({capabilities: {...CAPABILITIES, features: {auth: true}}});
  await h.start(); assert.equal(h.client.state.connection.status, 'auth_required');
  await h.client.login('discard-this-password');
  const socket = h.sockets.at(-1);
  socket.config.auth(data => assert.deepEqual(data, {token: 'session-secret'}));
  assert.equal(h.storage.session.data.jarvisSession.token, 'session-secret');
  assert.doesNotMatch(JSON.stringify(h.storage.local.data), /secret|password|token/);
  assert.doesNotMatch(JSON.stringify(h.storage.session.data), /discard-this-password/);
  assert.equal(socket.url, ORIGIN);
  socket.receive('connected');
  await h.client.send('Keep working');
  socket.receive('auth:required', {code: 'authentication_required'});
  await h.client.writeQueue;
  assert.equal(h.client.token, '');
  assert.equal(h.client.pendingRequestId, ID);
  assert.equal(h.client.state.connection.status, 'auth_required');
  h.client.close();
});

test('server switch invalidates a deferred connection permission result', async () => {
  let release;
  const h = harness(); await h.client.restore(); await h.client.configure({serverUrl: ORIGIN});
  h.client.permissions = {contains: ({origins}) => origins[0].includes('jarvis.example') ?
    new Promise(resolve => { release = resolve; }) : Promise.resolve(true)};
  const connecting = h.client.connect();
  await h.client.configure({serverUrl: 'https://second.example'});
  release(true); await connecting;
  assert.equal(h.client.state.settings.serverUrl, 'https://second.example');
  assert.equal(h.requests.length, 0); assert.equal(h.sockets.length, 0);
});

test('unacknowledged sends recover by UUID after background restart without replay', async () => {
  const h = harness(); await h.start(); await h.client.send('Why did this fail?');
  await h.client.writeQueue;
  assert.equal(h.sockets[0].sent.filter(event => event.name === 'chat:send').length, 1);
  h.client.close();
  const restored = harness({storage: h.storage});
  await restored.client.restore(); await restored.client.connect();
  const socket = restored.sockets[0]; socket.receive('connected');
  assert.deepEqual(socket.sent, [{name: 'chat:resume', data: {request_id: ID}}]);
  socket.receive('conversation:loaded', {conversation: {id: 'unrelated', messages: []}});
  assert.equal(restored.client.pendingRequestId, ID);
  assert.notEqual(restored.client.state.conversationId, 'unrelated');
  socket.receive('conversation:loaded', {conversation: {id: 'conversation-a', messages: [
    {role: 'user', content: 'Why did this fail?', data: {_request_id: ID}},
  ], run: {message_id: ID, conversation_id: 'conversation-a', status: 'running'}}});
  assert.equal(restored.client.pendingRequestId, null);
  assert.equal(restored.client.isActive(), true);
  await restored.client.cancel();
  assert.deepEqual(socket.sent.at(-1), {name: 'chat:cancel', data: {conversation_id: 'conversation-a', message_id: ID}});
  restored.client.close();
});

test('late events cannot replace a successor turn; response uses full text and cancellation', async () => {
  const h = harness(); await h.start(); const socket = h.sockets[0];
  await h.client.send('first');
  socket.receive('conversation:created', {conversation_id: 'conversation-a'});
  socket.receive('chat:thinking', {message_id: ID, conversation_id: 'conversation-a'});
  socket.receive('chat:response', {message_id: ID, conversation_id: 'conversation-a', text: 'Full answer', speech: 'Short', cancelled: true});
  assert.equal(h.client.state.messages.at(-1).content, 'Full answer');
  assert.equal(h.client.state.run.status, 'cancelled');
  await h.client.send('second');
  for (const name of ['chat:response', 'chat:error', 'chat:run', 'chat:thinking', 'tool:complete']) {
    socket.receive(name, {message_id: ID, conversation_id: 'conversation-a', status: 'completed', text: 'Stale'});
  }
  assert.equal(h.client.pendingRequestId, NEXT);
  assert.equal(h.client.state.run.messageId, NEXT);
  assert.equal(h.client.state.run.status, 'sending');
  h.client.close();
});

test('saved final answer and live final event deduplicate', async () => {
  const h = harness(); await h.start();
  await h.client.loadConversation('conversation-a');
  const socket = h.sockets[0];
  socket.receive('conversation:loaded', {conversation: {id: 'conversation-a', messages: [
    {role: 'assistant', content: 'Saved full answer', data: {_web_message_id: ID}},
  ], run: {message_id: ID, conversation_id: 'conversation-a', status: 'completed'}}});
  socket.receive('chat:response', {message_id: ID, conversation_id: 'conversation-a', text: 'Saved full answer'});
  assert.equal(h.client.state.messages.length, 1);
  h.client.close();
});

test('load errors refer to the requested conversation and leave the current view intact', async () => {
  const h = harness(); await h.start(); h.client.state.conversationId = 'conversation-a';
  await h.client.loadConversation('conversation-b');
  h.sockets[0].receive('chat:error', {conversation_id: 'conversation-b', error: 'Conversation missing'});
  assert.equal(h.client.state.notice, 'Conversation missing');
  assert.equal(h.client.state.connection.status, 'connected');
  assert.equal(h.client.state.conversationId, 'conversation-a'); h.client.close();
});

test('non-admission restores the submitted draft and removes the optimistic bubble', async () => {
  for (const event of ['chat:rejected', 'chat:error']) {
    const h = harness(); await h.start();
    await h.client.setDraft('Please keep this draft'); await h.client.send();
    h.sockets[0].receive(event, {message_id: ID, admitted: false, error: 'Busy'});
    assert.equal(h.client.state.draft.text, 'Please keep this draft');
    assert.equal(h.client.state.messages.length, 0); assert.equal(h.client.pendingRequestId, null);
    h.client.close();
  }
});

test('capture remains local until send; upload sends bounded JPEG and only metadata reaches chat', async () => {
  const h = harness(); await h.start();
  const attachment = {previewUrl: 'data:image/jpeg;base64,/9j/2Q==', width: 1024, height: 640,
    source: {title: 'Sample page', url: 'https://page.example'}, capturedAt: '2026-09-14T12:00:00Z'};
  await h.client.stage({attachment});
  assert.equal(h.requests.filter(item => item.url.includes('upload')).length, 0);
  await h.client.send('Explain');
  const upload = h.requests.find(item => item.url.endsWith('/api/upload-image'));
  assert.equal(upload.init.body.get('image').type, 'image/jpeg');
  assert.equal(upload.init.body.get('include_base64'), 'false');
  assert.equal(upload.init.credentials, 'omit'); assert.equal(upload.init.redirect, 'error');
  const send = h.sockets[0].sent.find(item => item.name === 'chat:send');
  assert.deepEqual(send.data.image, {action: 'analyze', images: [{filename: 'upload_test.jpg', url: '/api/uploads/upload_test.jpg'}]});
  assert.doesNotMatch(JSON.stringify(send), /base64/); h.client.close();
});

test('failed image upload retains the preview and sends no chat request', async () => {
  const h = harness({uploadFailure: true}); await h.start();
  await h.client.stage({attachment: {previewUrl: 'data:image/jpeg;base64,/9j/2Q==', width: 10, height: 10}});
  await assert.rejects(h.client.send('Retain me'), /reach Jarvis/);
  assert.ok(h.client.state.draft.attachment);
  assert.equal(h.client.pendingRequestId, null);
  assert.equal(h.sockets[0].sent.length, 0); h.client.close();
});

test('mode must be acknowledged before the next send', async () => {
  const h = harness(); await h.start(); await h.client.setMode('local');
  await assert.rejects(h.client.send('Too soon'), /Wait/);
  h.sockets[0].receive('mode:changed', {mode: 'local'}); await h.client.send('Ready');
  assert.equal(h.sockets[0].sent.at(-1).data.mode, 'local'); h.client.close();
});

test('rejection preserves newly typed draft while marking the rejected content', async () => {
  const h = harness(); await h.start(); await h.client.send('First question');
  await h.client.setDraft('A newer question');
  h.sockets[0].receive('chat:rejected', {message_id: ID, error: 'Busy'});
  assert.equal(h.client.state.draft.text, 'A newer question');
  assert.match(h.client.state.messages[0].content, /^\[Not sent/);
  assert.match(h.client.state.messages[0].content, /First question/); h.client.close();
});

test('accepted recovery clears only the unchanged submitted draft from a pre-send checkpoint', async () => {
  for (const changed of [false, true]) {
    const h = harness(); await h.start(); await h.client.send('Submitted question');
    h.client.state.draft = changed ? {text: 'Newer question', attachment: null, context: null} : structuredClone(h.client.pendingDraft);
    await h.client.checkpoint(); h.client.close();
    const restored = harness({storage: h.storage});
    await restored.client.restore(); await restored.client.connect(); const socket = restored.sockets[0];
    socket.receive('connected');
    socket.receive('conversation:loaded', {conversation: {id: 'conversation-a', messages: [
      {role: 'user', content: 'Submitted question', data: {_request_id: ID}},
    ], run: {message_id: ID, conversation_id: 'conversation-a', status: 'running'}}});
    assert.equal(restored.client.state.draft.text, changed ? 'Newer question' : '');
    assert.equal(restored.client.pendingDraft, null); restored.client.close();
  }
});
