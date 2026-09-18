import test from 'node:test';
import assert from 'node:assert/strict';
import {JarvisClient} from '../core/client.js';

const ORIGIN = 'https://jarvis.example';
const ID = '9c892f85-b79a-44c3-9be1-6b66d2f73145';
const NEXT = '9c892f85-b79a-44c3-9be1-6b66d2f73146';
const CAPABILITIES = {features: {auth: false}, extension: {api: 1, socket_auth: true,
  features: {chat: true, images: true, conversations: true, recovery: true, cancel: true, text: true}}};
const TEXT_REF = 'stash://space_web_text_0123456789abcdef0123456789abcdef/f_0123456789ab';
const PAGE = {
  title: 'Install guide', url: 'https://page.example/install',
  markdown: '# Install guide\n\n- URL: https://page.example/install\n\n## Page\nUse uv.\n',
  charCount: 72, truncated: false, capturedAt: '2026-09-15T12:00:00Z',
  filename: 'browser-page.md', uploadId: '9c892f85-b79a-44c3-9be1-6b66d2f73147',
};
const PAGE_LINK = {title: 'A YouTube video', url: 'https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=120'};
const tick = () => new Promise(resolve => setImmediate(resolve));

test('late task events preserve an active turn, progress and draft, and deduplicate answers', async () => {
  const h=harness();await h.start();
  const socket=h.sockets[0];
  h.client.restoringConversation=ID;
  socket.receive('conversation:loaded',{conversation:{id:ID,generation:2,messages:[
    {role:'assistant',content:'Queued',data:{_web_message_id:'first'}}
  ],run:{message_id:'second',conversation_id:ID,status:'running',mode:'cloud',kind:'chat'}}});
  socket.receive('tool:start',{conversation_id:ID,message_id:'second',tool:'get_time'});
  await h.client.setDraft('Keep my unsent follow-up');
  const before=structuredClone({run:h.client.state.run,progress:h.client.state.progress,draft:h.client.state.draft});
  const job={schema_version:1,conversation_id:ID,generation:2,job_id:'job',source_message_id:'first',
    tool:'fixture',state:'succeeded',revision:4,result:{summary:'<script>inert</script>'}};
  socket.receive('task:updated',job);
  socket.receive('task:updated',{...job,revision:2,state:'running'});
  const late={schema_version:1,conversation_id:ID,generation:2,continuation_id:'late',message:{content:'Fixture finished'}};
  socket.receive('chat:continuation',late);socket.receive('chat:continuation',late);
  assert.deepEqual({run:h.client.state.run,progress:h.client.state.progress,draft:h.client.state.draft},before);
  assert.equal(h.client.state.messages.filter(message=>message.id==='assistant-late').length,1);
  assert.equal(h.client.state.messages[0].backgroundJobs[0].status,'succeeded');
  socket.receive('chat:continuation',{...late,continuation_id:'stale',generation:1});
  socket.receive('chat:continuation',{...late,continuation_id:'elsewhere',conversation_id:NEXT});
  assert.equal(h.client.state.messages.length,2);
  h.client.restoringConversation=ID;
  socket.receive('conversation:loaded',{conversation:{id:ID,generation:1,messages:[]}});
  assert.equal(h.client.state.conversationGeneration,2);
  assert.equal(h.client.state.messages.length,2);
  h.client.close();
});

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
    if (url.endsWith('/api/profile-appearance')) {
      if (options.profileFailure) throw new Error('profile unavailable');
      body = {ok: true, profile: typeof options.profile === 'function' ? await options.profile() : options.profile};
    }
    if (url.includes('/api/conversations?')) body.conversations = [];
    if (url.endsWith('/api/auth/login')) body.token = 'session-secret';
    if (url.endsWith('/api/upload-image')) {
      if (options.uploadFailure) throw new Error('offline');
      body = {ok: true, filename: 'upload_test.jpg', url: '/api/uploads/upload_test.jpg'};
    }
    if (url.endsWith('/api/upload-text')) {
      if (options.textUploadFailure) throw new Error('offline');
      body = {ok: true, attachment: {kind: 'text', stash_ref: TEXT_REF, filename: 'browser-page.md',
        upload_id: PAGE.uploadId}};
    }
    return {ok: true, status: 200, json: async () => body};
  };
  const ioFactory = (url, config) => {
    const socket = {url, config, handlers: {}, sent: [], connected: false,
      on(name, fn) { this.handlers[name] = fn; },
      connect() { this.connected = true; },
      emit(name, data) {
        if (name === 'chat:send') {
          assert.equal(storage.session.data.jarvisSession.pendingRequestId, data.request_id);
          assert.equal(storage.session.data.jarvisSession.state.submittedRequests.at(-1).requestId, data.request_id);
        }
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

test('an old private-LAN HTTP setting cannot reconnect or check completions after an update', async () => {
  const storage = {local: area({jarvisSettings: {serverUrl: 'http://192.168.1.2:5001', allowInsecureLocal: true}}), session: area()};
  const h = harness({storage});
  await h.client.restore();
  await assert.rejects(h.client.connect(), /HTTPS is required/);
  await assert.rejects(h.client.completionReader(), /HTTPS is required/);
  await assert.rejects(h.client.configure({serverUrl: 'http://10.0.0.2:5001', allowInsecureLocal: true}), /HTTPS is required/);
  assert.equal(h.requests.length, 0, 'Reject before transmitting credentials or other data');
  assert.equal(h.sockets.length, 0);
  await h.client.configure({serverUrl: ORIGIN});
  await h.client.connect();
  assert.ok(h.requests.every(request => request.url.startsWith(ORIGIN + '/')));
  assert.equal(h.sockets.length, 1, 'Changing to HTTPS restores the normal connection');
  h.client.close();
});

test('the current tab is never added to an ordinary message without Include page', async () => {
  const h = harness(); await h.start();
  h.client.state.source = PAGE_LINK;
  await h.client.send('Write a grocery list');
  const sent = h.sockets[0].sent.at(-1).data;
  assert.equal(sent.message, 'Write a grocery list');
  assert.equal(sent.tool_hints, undefined);
  h.client.close();
});

test('an included page is a durable local snapshot until Send, then clears with a transcript hint', async () => {
  const h = harness(); await h.start();
  const count = h.requests.length;
  await h.client.setDraft("What's this video about?");
  const source = {...PAGE_LINK};
  await h.client.includePage(source);
  source.url = 'https://example.test/switched-tab';
  assert.equal(h.requests.length, count, 'Including a link never fetches the page or server');
  const restored = harness({storage: h.storage}); await restored.client.restore();
  assert.deepEqual(restored.client.state.draft.pageLink, PAGE_LINK);
  await h.client.send();
  const sent = h.sockets[0].sent.at(-1).data;
  assert.ok(sent.message.startsWith("What's this video about?"));
  assert.ok(sent.message.includes(PAGE_LINK.url));
  assert.ok(!sent.message.includes(source.url));
  assert.deepEqual(sent.tool_hints, ['youtube_transcript']);
  assert.equal(sent.image, undefined);
  assert.equal(sent.attachments, undefined);
  assert.equal(h.requests.length, count);
  assert.equal(h.client.state.draft.pageLink, null);
  assert.deepEqual(h.client.pendingDraft.pageLink, PAGE_LINK);
  h.client.close();
});

test('including and removing a link preserve the question, screenshot, page text and selection', async () => {
  const h = harness(); await h.start();
  await h.client.setDraft('My question');
  await h.client.stage({page: PAGE, attachment: {previewUrl:'data:image/jpeg;base64,/9j/2Q==',width:10,height:10},
    context:{title:'Selection',url:PAGE_LINK.url,text:'Selected words'}});
  const before = structuredClone(h.client.state.draft);
  await h.client.includePage(PAGE_LINK);
  assert.deepEqual(h.client.state.draft, {...before, pageLink:PAGE_LINK});
  await h.client.removePageLink();
  assert.deepEqual(h.client.state.draft, before);
  await h.client.includePage(PAGE_LINK);
  h.client.state.mode = 'local';
  await h.client.send();
  const sent = h.sockets[0].sent.at(-1).data;
  assert.ok(sent.image);
  assert.equal(sent.attachments.length, 1, 'A page link does not consume a file-source slot');
  assert.match(sent.message, /Selected words/);
  assert.deepEqual(sent.tool_hints, ['youtube_transcript']);
  h.client.close();
});

test('removed links, new conversations and ordinary pages do not carry a YouTube hint', async () => {
  const h = harness(); await h.start();
  await h.client.includePage(PAGE_LINK); await h.client.removePageLink();
  await h.client.send('Unrelated question');
  assert.equal(h.sockets[0].sent.at(-1).data.tool_hints, undefined);
  assert.doesNotMatch(h.sockets[0].sent.at(-1).data.message, /youtube/);
  h.client.close();
  const fresh = harness(); await fresh.start();
  await fresh.client.includePage(PAGE_LINK); await fresh.client.newConversation();
  assert.equal(fresh.client.state.draft.pageLink, null);
  fresh.client.close();
  const ordinary = harness(); await ordinary.start();
  await ordinary.client.includePage({url:'https://example.test/article',title:'Article'});
  await ordinary.client.send('Summarize this');
  assert.equal(ordinary.sockets[0].sent.at(-1).data.tool_hints, undefined);
  ordinary.client.close();
});

test('rejected send restores the included link without overwriting a newer link-only draft', async () => {
  for (const newer of [null, {title:'New page',url:'https://example.test/new'}]) {
    const h = harness(); await h.start();
    await h.client.includePage(PAGE_LINK); await h.client.send('Summarize');
    if (newer) h.client.state.draft.pageLink = newer;
    h.sockets[0].receive('chat:rejected', {message_id:ID,error:'Busy'});
    assert.deepEqual(h.client.state.draft.pageLink, newer || PAGE_LINK);
    h.client.close();
  }
});

test('link-only requests work without text uploads and slash commands keep their own routing', async () => {
  for (const text of ['', '/research this video']) {
    const h = harness({capabilities: {...CAPABILITIES, extension: {...CAPABILITIES.extension,
      features: {...CAPABILITIES.extension.features, text: false}}}});
    await h.start();
    await h.client.includePage(PAGE_LINK);
    await h.client.send(text);
    const sent = h.sockets[0].sent.at(-1).data;
    assert.ok(sent.message.includes(PAGE_LINK.url));
    assert.ok(sent.message.startsWith(text || 'Summarize this video using its transcript.'));
    assert.deepEqual(sent.tool_hints, text ? undefined : ['youtube_transcript']);
    assert.equal(h.requests.some(request => request.url.includes('/api/upload-')), false);
    h.client.close();
  }
});

const PROFILE_CAPABILITIES = {...CAPABILITIES, extension: {...CAPABILITIES.extension,
  features: {...CAPABILITIES.extension.features, profile: true}}};
const PROFILE = {display_name: 'Morgan', avatar: 'data:image/png;base64,iVBORw0KGgo='};

test('profile is authenticated, refreshed on change, and omitted from recovery storage', async () => {
  let profile = PROFILE;
  const h = harness({capabilities: {...PROFILE_CAPABILITIES, features: {auth: true}}, profile: () => profile});
  await h.start();
  assert.equal(h.requests.some(request => request.url.endsWith('/api/profile-appearance')), false);
  await h.client.login('test');
  h.sockets.at(-1).receive('connected');
  await tick();
  assert.deepEqual(h.client.state.profile, PROFILE);
  const request = h.requests.find(request => request.url.endsWith('/api/profile-appearance'));
  assert.equal(request.init.headers.Authorization, 'Bearer session-secret');
  assert.equal(request.init.credentials, 'omit');
  profile = {display_name: 'Alex', avatar: null};
  h.sockets.at(-1).receive('profile:changed');
  await tick();
  assert.deepEqual(h.client.state.profile, profile);
  await h.client.checkpoint();
  assert.equal(h.storage.session.data.jarvisSession.state.profile, null);
  assert.doesNotMatch(JSON.stringify(h.storage.local.data), /Morgan|Alex|iVBOR/);
  await h.client.logout();
  assert.equal(h.client.state.profile, null);
});

test('older servers and unavailable appearance still allow chat', async () => {
  const old = harness(); await old.start();
  assert.equal(old.requests.some(request => request.url.endsWith('/api/profile-appearance')), false);
  assert.equal(old.client.state.profile, null);
  const h = harness({capabilities: PROFILE_CAPABILITIES, profileFailure: true});
  await h.start();
  assert.equal(h.client.state.connection.status, 'connected');
  await h.client.send('Still usable');
  assert.equal(h.sockets.at(-1).sent.at(-1).name, 'chat:send');
});

test('a stale profile response cannot cross a server change or sign-out', async () => {
  for (const action of ['switch', 'logout']) {
    let resolve;
    const h = harness({capabilities: PROFILE_CAPABILITIES, profile: () => new Promise(done => { resolve = done; })});
    await h.start();
    if (action === 'switch') await h.client.configure({serverUrl: 'https://another.example'});
    else await h.client.logout();
    resolve(PROFILE);
    await tick();
    assert.equal(h.client.state.profile, null);
  }
});

test('the latest profile refresh wins over an older in-flight response', async () => {
  const resolves = [];
  const h = harness({capabilities: PROFILE_CAPABILITIES, profile: () => new Promise(done => resolves.push(done))});
  await h.start();
  h.sockets.at(-1).receive('profile:changed');
  await tick();
  resolves[1]({display_name: 'Latest', avatar: null});
  await tick();
  resolves[0](PROFILE);
  await tick();
  assert.equal(h.client.state.profile.display_name, 'Latest');
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
    assert.equal(h.client.state.run.status, 'failed', 'the existing error presentation stays intact');
    assert.equal(h.client.state.submittedRequests[0].status, 'rejected', 'unadmitted work does not trigger a completion alert');
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

test('page text stays local until send and is uploaded as a durable text source', async () => {
  const h = harness(); await h.start();
  await h.client.stage({page: PAGE});
  assert.equal(h.requests.filter(item => item.url.includes('upload')).length, 0);
  await h.client.send('What does this page require?');
  const upload = h.requests.find(item => item.url.endsWith('/api/upload-text'));
  assert.equal(upload.init.body.get('file').type, 'text/markdown');
  assert.equal(upload.init.body.get('upload_id'), PAGE.uploadId);
  const send = h.sockets[0].sent.find(item => item.name === 'chat:send');
  assert.deepEqual(send.data.attachments, [{kind: 'text', stash_ref: TEXT_REF, filename: 'browser-page.md', upload_id: PAGE.uploadId}]);
  assert.doesNotMatch(send.data.message, /Use uv/);
  assert.equal(send.data.image, undefined);
  h.client.close();
});

test('screenshot plus page text uploads both and keeps page body out of the chat message', async () => {
  const h = harness(); await h.start();
  await h.client.stage({
    attachment: {previewUrl: 'data:image/jpeg;base64,/9j/2Q==', width: 1024, height: 640,
      source: {title: 'Install guide', url: PAGE.url}, capturedAt: PAGE.capturedAt},
    page: PAGE,
  });
  await h.client.send('');
  const send = h.sockets[0].sent.find(item => item.name === 'chat:send');
  assert.ok(h.requests.some(item => item.url.endsWith('/api/upload-image')));
  assert.ok(h.requests.some(item => item.url.endsWith('/api/upload-text')));
  assert.equal(send.data.image.action, 'analyze');
  assert.equal(send.data.attachments[0].stash_ref, TEXT_REF);
  assert.match(send.data.message, /attached page text/);
  assert.doesNotMatch(send.data.message, /Use uv/);
  h.client.close();
});

test('staged selection remains in the outgoing request when page text is also attached', async () => {
  const h = harness(); await h.start();
  await h.client.stage({
    page: PAGE,
    context: {kind: 'selection', title: 'Install guide', url: PAGE.url, text: 'The worker must use CUDA 12.'},
  });
  await h.client.send('Compare this requirement');
  const send = h.sockets[0].sent.find(item => item.name === 'chat:send');
  assert.match(send.data.message, /CUDA 12/);
  assert.match(send.data.message, /Browser content supplied for reference/);
  assert.equal(send.data.attachments[0].stash_ref, TEXT_REF);
  h.client.close();
});

test('older servers without page-text still connect for chat and screenshots', async () => {
  const features = {chat: true, images: true, conversations: true, recovery: true, cancel: true};
  const h = harness({capabilities: {features: {auth: false}, extension: {api: 1, socket_auth: true, features}}});
  await h.start();
  assert.equal(h.client.state.connection.status, 'connected');
  assert.equal(h.client.state.capabilities.text, false);
  await h.client.stage({page: PAGE});
  await assert.rejects(h.client.send('Keep this page'), /cannot store captured page text/);
  assert.equal(h.sockets[0].sent.length, 0);
  await h.client.removePage();
  await h.client.send('Hello from an older server');
  assert.equal(h.sockets[0].sent.at(-1).name, 'chat:send');
  h.client.close();
});

test('failed page-text upload retains the staged page and sends no chat request', async () => {
  const h = harness({textUploadFailure: true}); await h.start();
  await h.client.stage({page: PAGE});
  await assert.rejects(h.client.send('Keep this page'), /reach Jarvis/);
  assert.equal(h.client.state.draft.page.markdown, PAGE.markdown);
  assert.equal(h.client.pendingRequestId, null);
  assert.equal(h.sockets[0].sent.length, 0); h.client.close();
});

test('rejection restores a submitted page and keeps a later staged page', async () => {
  const h = harness(); await h.start();
  await h.client.stage({page: PAGE});
  const submitted = structuredClone(h.client.state.draft.page);
  await h.client.send('First capture');
  h.sockets[0].receive('chat:rejected', {message_id: ID, error: 'Busy'});
  assert.deepEqual(h.client.state.draft.page, submitted);
  h.client.close();

  const later = harness(); await later.start();
  await later.client.stage({page: PAGE});
  await later.client.send('First capture');
  const newer = {...PAGE, uploadId: '9c892f85-b79a-44c3-9be1-6b66d2f73148', markdown: '# Newer page\n'};
  later.client.state.draft.page = newer;
  later.sockets[0].receive('chat:rejected', {message_id: ID, error: 'Busy'});
  assert.equal(later.client.state.draft.page.markdown, newer.markdown);
  assert.match(later.client.state.messages[0].content, /^\[Not sent/);
  later.client.close();
});

test('restored conversations keep page-text attachment labels', async () => {
  const h = harness(); await h.start();
  await h.client.loadConversation('conversation-a');
  h.sockets[0].receive('conversation:loaded', {conversation: {
    id: 'conversation-a',
    messages: [{
      role: 'user', content: 'Review this page',
      data: {
        _request_id: ID,
        image_url: '/api/uploads/upload_test.jpg',
        attachments: [{kind: 'text', filename: 'browser-page.md'}],
      },
    }],
    run: {message_id: ID, conversation_id: 'conversation-a', status: 'completed'},
  }});
  assert.deepEqual(h.client.state.messages[0].attachments, [
    {label: 'Screenshot / image'},
    {label: 'browser-page.md'},
  ]);
  h.client.close();
});

test('removing page text keeps a staged screenshot', async () => {
  const h = harness(); await h.start();
  await h.client.stage({
    attachment: {previewUrl: 'data:image/jpeg;base64,/9j/2Q==', width: 10, height: 10},
    page: PAGE,
  });
  await h.client.removePage();
  assert.equal(h.client.state.draft.page, null);
  assert.ok(h.client.state.draft.attachment);
  h.client.close();
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
    h.client.state.draft = changed ? {text: 'Newer question', attachment: null, context: null, page: null, pageLink: null} : structuredClone(h.client.pendingDraft);
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

const IMAGE_URL = 'https://images.example/photo.png?size=large&v=2';
const imageContext = () => ({kind: 'image', url: IMAGE_URL, title: 'Image source', text: ''});

test('image action stages an editable URL, preserves draft, and sends a separate tool hint only on Send', async () => {
  const h = harness(); await h.start();
  await h.client.setDraft('Please focus on the damaged corner.');
  const requestCount = h.requests.length;
  await h.client.stage({context: imageContext()});
  assert.equal(h.requests.length, requestCount, 'staging does not fetch the image or the server');
  assert.equal(h.sockets[0].sent.length, 0, 'staging does not send work');
  assert.equal(h.client.state.draft.text, `Please focus on the damaged corner.\n\nAnalyze this image:\n${IMAGE_URL}`);
  assert.equal(h.client.state.draft.context.kind, 'image');
  await h.client.setDraft(`Is this repairable?\n${IMAGE_URL}`);
  await h.client.send();
  const send = h.sockets[0].sent.at(-1);
  assert.equal(send.data.message, `Is this repairable?\n${IMAGE_URL}`);
  assert.deepEqual(send.data.tool_hints, ['analyze_image']);
  assert.equal(send.data.image, undefined, 'remote URL does not use the screenshot upload contract');
  assert.equal(h.requests.some(item => item.url.includes('upload-image')), false);
  assert.deepEqual(h.client.state.draft, {text: '', attachment: null, context: null, page: null, pageLink: null});
  h.client.close();
});

test('a delayed edit from before image staging preserves both the typed draft and newly staged image', async () => {
  const h = harness(); await h.start();
  await h.client.setDraft('Previously saved text', {imageStageId: null});
  await h.client.stage({context: imageContext()});
  const stageId = h.client.state.draft.context.stageId;
  await h.client.setDraft('Newer unsaved wording', {imageStageId: null});
  assert.equal(h.client.state.draft.context.stageId, stageId);
  assert.equal(h.client.state.draft.text, `Newer unsaved wording\n\nAnalyze this image:\n${IMAGE_URL}`);
  await h.client.setDraft(h.client.state.draft.text, {imageStageId: stageId});
  assert.equal(h.client.state.draft.text.split(IMAGE_URL).length, 2, 'acknowledging the merge does not duplicate the image');
  await h.client.send();
  assert.deepEqual(h.sockets[0].sent.at(-1).data.tool_hints, ['analyze_image']); h.client.close();
});

test('restaging even the same image gets a new identity and resists edits tied to the earlier stage', async () => {
  const h = harness(); await h.start(); await h.client.stage({context: imageContext()});
  const oldStageId = h.client.state.draft.context.stageId;
  await h.client.stage({context: imageContext()});
  const stageId = h.client.state.draft.context.stageId;
  assert.notEqual(stageId, oldStageId);
  assert.equal(h.client.state.draft.text.split(IMAGE_URL).length, 2);
  await h.client.setDraft('I revised this while the image was staged again.', {imageStageId: oldStageId});
  assert.equal(h.client.state.draft.context.stageId, stageId);
  assert.match(h.client.state.draft.text, /^I revised this/);
  assert.ok(h.client.state.draft.text.includes(IMAGE_URL));
  await h.client.checkpoint(); const restored = harness({storage: h.storage}); await restored.client.restore();
  assert.equal(restored.client.state.draft.context.stageId, stageId);
  h.client.close(); restored.client.close();
});

test('edits that observed an image stage can remove it and stale edits cannot restore its hint', async () => {
  const h = harness(); await h.start(); await h.client.stage({context: imageContext()});
  const stageId = h.client.state.draft.context.stageId;
  await h.client.setDraft('I removed the image deliberately.', {imageStageId: stageId});
  assert.equal(h.client.state.draft.context, null);
  await h.client.setDraft(`An older draft with ${IMAGE_URL}`, {imageStageId: stageId});
  assert.equal(h.client.state.draft.context, null);
  await h.client.send();
  assert.equal(h.sockets[0].sent.at(-1).data.tool_hints, undefined); h.client.close();
});

test('an oversized stale edit cannot truncate or discard a newly staged image', async () => {
  const h = harness(); await h.start(); await h.client.stage({context: imageContext()});
  const saved = structuredClone(h.client.state.draft);
  await assert.rejects(h.client.setDraft('x'.repeat(32000), {imageStageId: null}), /too long/);
  assert.deepEqual(h.client.state.draft, saved); h.client.close();
});

test('nonshareable and credential-bearing image URLs leave the existing draft intact', async () => {
  for (const url of ['blob:https://page.example/uuid', 'data:image/png;base64,AAAA', 'file:///tmp/private.png',
    'javascript:alert(1)', 'https://user:secret@example.com/image.png', 'not a URL']) {
    const h = harness(); await h.start(); await h.client.setDraft('Keep this');
    await assert.rejects(h.client.stage({context: {...imageContext(), url}}), /Capture page view/);
    assert.equal(h.client.state.draft.text, 'Keep this');
    assert.equal(h.client.state.draft.context, null);
    assert.equal(h.sockets[0].sent.length, 0);
    h.client.close();
  }
});

test('oversized image staging retains the original draft without a truncated URL', async () => {
  const h = harness(); await h.start(); await h.client.setDraft('x'.repeat(32000));
  await assert.rejects(h.client.stage({context: imageContext()}), /too long/);
  assert.equal(h.client.state.draft.text.length, 32000);
  assert.equal(h.client.state.draft.context, null); h.client.close();
});

test('image hints clear after removing context or editing away the URL, and never attach to workflows', async () => {
  for (const change of ['remove', 'replace', 'workflow', 'other-context']) {
    const h = harness(); await h.start(); await h.client.stage({context: imageContext()});
    if (change === 'remove') await h.client.removeContext();
    if (change === 'replace') await h.client.setDraft('Ask an unrelated question');
    if (change === 'workflow') await h.client.setDraft(`/deep_dive ${IMAGE_URL}`);
    if (change === 'other-context') await h.client.stage({context: {kind: 'link', url: 'https://example.com/page', text: '', title: 'A different page'}});
    await h.client.send();
    assert.equal(h.sockets[0].sent.at(-1).data.tool_hints, undefined);
    h.client.close();
  }
});

test('image hints do not leak across mode or conversation switches', async () => {
  for (const change of ['mode', 'load', 'new']) {
    const h = harness(); await h.start(); await h.client.stage({context: imageContext()});
    const draft = h.client.state.draft.text;
    if (change === 'mode') {
      await h.client.setMode('local'); h.sockets[0].receive('mode:changed', {mode: 'local'});
    } else if (change === 'load') {
      await h.client.loadConversation('conversation-b');
      h.sockets[0].receive('conversation:loaded', {conversation: {id: 'conversation-b', messages: []}});
    } else {
      await h.client.newConversation(); h.sockets.at(-1).receive('connected');
    }
    assert.equal(h.client.state.draft.context, null);
    assert.equal(h.client.state.draft.text, change === 'new' ? '' : draft);
    await h.client.send('Another question');
    assert.equal(h.sockets.at(-1).sent.at(-1).data.tool_hints, undefined); h.client.close();
  }
});

test('rejected image send restores its draft and hint; accepted recovery clears the submitted draft', async () => {
  const h = harness(); await h.start(); await h.client.stage({context: imageContext()});
  const draft = structuredClone(h.client.state.draft); await h.client.send();
  h.sockets[0].receive('chat:rejected', {message_id: ID, error: 'Busy'});
  assert.deepEqual(h.client.state.draft, draft);
  assert.equal(h.client.state.submittedRequests[0].status, 'rejected');
  await h.client.send();
  assert.deepEqual(h.sockets[0].sent.at(-1).data.tool_hints, ['analyze_image']);
  h.client.state.draft = structuredClone(h.client.pendingDraft);
  await h.client.checkpoint(); h.client.close();
  const restored = harness({storage: h.storage}); await restored.client.restore(); await restored.client.connect();
  const socket = restored.sockets[0]; socket.receive('connected');
  socket.receive('conversation:loaded', {conversation: {id: 'conversation-a', messages: [
    {role: 'user', content: draft.text, data: {_request_id: NEXT}},
  ], run: {message_id: NEXT, conversation_id: 'conversation-a', status: 'running'}}});
  assert.deepEqual(restored.client.state.draft, {text: '', attachment: null, context: null, page: null, pageLink: null});
  assert.equal(restored.client.state.submittedRequests[1].conversationId, 'conversation-a');
  assert.equal(restored.client.state.submittedRequests[1].status, 'running');
  restored.client.close();
});

test('preferences use safe defaults, accept only booleans, and survive server changes without a reconnect', async () => {
  const h = harness(); await h.start(); const transport = h.client.transport;
  assert.deepEqual(h.client.state.settings.preferences, {showBadge: true, desktopNotifications: false, notificationPreview: false});
  await h.client.updatePreferences({showBadge: false, desktopNotifications: true, notificationPreview: 'true', token: 'ignored'});
  assert.equal(h.client.transport, transport);
  assert.deepEqual(h.client.state.settings.preferences, {showBadge: false, desktopNotifications: true, notificationPreview: false});
  await h.client.configure({serverUrl: 'https://second.example'});
  assert.deepEqual(h.client.state.settings.preferences, {showBadge: false, desktopNotifications: true, notificationPreview: false});
  assert.doesNotMatch(JSON.stringify(h.storage.local.data), /ignored/);
  const restored = harness({storage: h.storage}); await restored.client.restore();
  assert.deepEqual(restored.client.state.settings.preferences, h.client.state.settings.preferences);
  h.client.close(); restored.client.close();
});

test('completion identity survives background restore and rotates at authentication boundaries', async () => {
  const h = harness(); await h.start(); await h.client.send('Observe only this extension request');
  const scope = h.client.authScope; await h.client.checkpoint(); h.client.close();
  const restored = harness({storage: h.storage}); await restored.client.restore();
  assert.equal(restored.client.authScope, scope);
  assert.equal(restored.client.state.submittedRequests[0].requestId, ID);
  await restored.client.logout();
  assert.notEqual(restored.client.authScope, scope);
  assert.deepEqual(restored.client.state.submittedRequests, []);
  const loggedOutScope = restored.client.authScope;
  restored.client.unauthorized();
  assert.notEqual(restored.client.authScope, loggedOutScope); restored.client.close();
});

test('only extension submissions enter completion tracking and terminal recovery does not keep polling', async () => {
  const h = harness(); await h.start(); const socket = h.sockets[0];
  socket.receive('chat:thinking', {message_id: NEXT, conversation_id: 'conversation-a'});
  socket.receive('chat:response', {message_id: NEXT, conversation_id: 'conversation-a', text: 'Other client'});
  assert.deepEqual(h.client.state.submittedRequests, []);
  await h.client.send('Extension task');
  socket.receive('chat:thinking', {message_id: ID, conversation_id: 'conversation-a'});
  assert.equal(h.client.state.submittedRequests[0].conversationId, 'conversation-a');
  socket.receive('chat:response', {message_id: ID, conversation_id: 'conversation-a', text: 'Finished'});
  assert.equal(h.client.state.submittedRequests[0].status, 'completed');
  h.client.close();
  const pending = harness(); await pending.start(); await pending.client.send('Maybe sent');
  pending.client.state.connection.status = 'recovering';
  pending.sockets[0].receive('chat:resume_missing', {});
  assert.equal(pending.client.state.submittedRequests[0].status, 'unconfirmed'); pending.client.close();
});

test('completion checkpoint retains bounded metadata without response or credential payloads', async () => {
  const h = harness(); await h.start();
  h.client.state.submittedRequests = Array.from({length: 80}, (_, index) => ({
    requestId: `request-${index}`, conversationId: 'conversation-a', mode: 'cloud', startedAt: '2026-09-14T12:00:00Z',
    status: 'completed', text: 'Do not keep response text here', token: 'Do not keep credentials here',
  }));
  await h.client.checkpoint();
  const records = h.storage.session.data.jarvisSession.state.submittedRequests;
  assert.equal(records.length, 64); assert.equal(records[0].requestId, 'request-16');
  assert.equal(records.some(record => 'text' in record || 'token' in record), false); h.client.close();
});

test('completion reads after background restore use authenticated HTTP without opening a socket or sending work', async () => {
  const h = harness(); await h.start(); h.client.token = 'test-token'; await h.client.send('Track this');
  await h.client.checkpoint(); h.client.close();
  const restored = harness({storage: h.storage}); await restored.client.restore();
  const reads = [];
  restored.client.fetchImpl = async (url, init) => {
    reads.push({url, init});
    return {ok: true, status: 200, json: async () => url.includes('?') ? {conversations: [
      {id: 'conversation-a', first_request_id: ID, last_request_id: NEXT},
    ]} : {conversation: {id: 'conversation-a', messages: []}}};
  };
  const found = await restored.client.findSubmittedConversation(restored.client.state.submittedRequests[0]);
  assert.equal(found.conversation.id, 'conversation-a');
  const direct = await restored.client.readConversation('conversation-a');
  assert.equal(direct.conversation.id, 'conversation-a');
  assert.equal(reads.length, 3);
  assert.ok(reads.every(({init}) => init.method === 'GET' && init.headers.Authorization === 'Bearer test-token' && init.credentials === 'omit'));
  assert.equal(restored.sockets.length, 0);
  assert.equal(restored.client.pendingRequestId, ID);
  assert.equal(restored.client.state.conversationId, null, 'polling does not change the selected conversation');
  await assert.rejects(restored.client.readConversation('../secret'), /Invalid conversation/);
  assert.equal(await restored.client.findSubmittedConversation({requestId: 'not-extension-work'}), null);
  assert.equal(reads.length, 3); restored.client.close();
});

test('completion polling honors removed permissions and a logout while permission checking', async () => {
  const h = harness(); await h.start(); let calls = 0;
  h.client.fetchImpl = async () => { calls++; throw new Error('Must not fetch'); };
  h.client.permissions = {contains: async () => false};
  await assert.rejects(h.client.readConversation('conversation-a'), /permission/);
  let release;
  h.client.permissions = {contains: () => new Promise(resolve => { release = resolve; })};
  const reading = h.client.readConversation('conversation-a');
  await h.client.logout(); release(true);
  await assert.rejects(reading, /connection changed/);
  assert.equal(calls, 0); h.client.close();
});

test('a delayed unauthorized poll cannot clear credentials for a newly configured server', async () => {
  const h = harness(); await h.start(); let release;
  h.client.fetchImpl = () => new Promise(resolve => { release = resolve; });
  const reading = h.client.readConversation('conversation-a'); await tick();
  await h.client.configure({serverUrl: 'https://second.example'});
  h.client.token = 'new-server-token'; const scope = h.client.authScope;
  release({ok: false, status: 401, json: async () => ({ok: false, error: 'Expired'})});
  await assert.rejects(reading, /Expired/);
  assert.equal(h.client.token, 'new-server-token'); assert.equal(h.client.authScope, scope);
  assert.notEqual(h.client.state.connection.status, 'auth_required'); h.client.close();
});

test('an unauthorized poll on the current server clears its auth scope and tracked requests', async () => {
  const h = harness(); await h.start(); await h.client.send('In progress');
  h.client.token = 'old-token'; const scope = h.client.authScope;
  h.client.fetchImpl = async () => ({ok: false, status: 401, json: async () => ({ok: false, error: 'Expired'})});
  await assert.rejects(h.client.readConversation('conversation-a'), /Expired/);
  assert.equal(h.client.token, ''); assert.notEqual(h.client.authScope, scope);
  assert.deepEqual(h.client.state.submittedRequests, []);
  assert.equal(h.client.state.connection.status, 'auth_required'); h.client.close();
});
