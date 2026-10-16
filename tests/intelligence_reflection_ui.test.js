/** Deterministic checks of the shipped classic scripts; no server or LLM calls. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');
const client = path.join(root, 'jarvis-intelligence/client');
const escape = value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');

class Element {
  constructor(tag = 'div') {
    this.tag = tag;
    this.dataset = {};
    this.events = {};
    this.style = {};
    this.attributes = {};
    this.children = [];
    this.nodes = [];
    this.isConnected = true;
    this.value = '';
    this.classList = { add() {}, remove() {}, toggle() {} };
    this._html = '';
    this._text = '';
  }
  set innerHTML(value) {
    this.nodes.forEach(node => { node.isConnected = false; });
    this.nodes = [];
    this._html = String(value);
    this._text = '';
    for (const match of this._html.matchAll(/<(button|details)\b([^>]*)>/g)) {
      const node = new Element(match[1]);
      for (const attr of match[2].matchAll(/([\w-]+)="([^"]*)"/g)) {
        node.attributes[attr[1]] = attr[2];
        if (attr[1] === 'class') node.className = attr[2];
        if (attr[1] === 'id') node.id = attr[2];
        if (attr[1].startsWith('data-')) {
          node.dataset[attr[1].slice(5).replace(/-([a-z])/g, (_, char) => char.toUpperCase())] = attr[2];
        }
      }
      node.disabled = /\sdisabled(?:\s|$)/.test(match[2]);
      node.hidden = /\shidden(?:\s|$)/.test(match[2]);
      if (node.className === 'reflection-review') {
        node.body = new Element();
        node.body.id = `reflectionReview${node.dataset.reflectionId}`;
      }
      this.nodes.push(node);
    }
  }
  get innerHTML() { return this._text ? escape(this._text) : this._html; }
  set textContent(value) { this._text = String(value); this._html = ''; }
  get textContent() { return this._text; }
  addEventListener(name, callback) { this.events[name] = callback; }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  querySelectorAll(selector) {
    return this.nodes.filter(node => (node.className || '').split(/\s+/).includes(selector.slice(1)));
  }
  querySelector(selector) { return selector === '.reflection-review-body' ? this.body : this.querySelectorAll(selector)[0]; }
  appendChild(node) { this.children.push(node); }
  remove() {}
}

function harness() {
  const elements = new Map();
  const html = fs.readFileSync(path.join(client, 'index.html'), 'utf8');
  for (const match of html.matchAll(/id="([^"]+)"/g)) elements.set(match[1], new Element());
  const container = elements.get('reflectionContent');
  const document = {
    addEventListener() {},
    createElement: tag => new Element(tag),
    getElementById: id => container.nodes.find(node => node.id === id) || elements.get(id) || null,
    querySelectorAll: selector => selector === '.reflection-mutation' ? container.querySelectorAll(selector) : []
  };
  const sandbox = vm.createContext({
    document, URLSearchParams, AbortController, console, Map, Set,
    localStorage: { getItem() { return null; }, setItem() {} },
    window: { location: { search: '' } },
    setTimeout() {}, clearTimeout() {}, confirm() { return true; }
  });
  vm.runInContext(fs.readFileSync(path.join(client, 'js/api.js'), 'utf8'), sandbox);
  vm.runInContext(fs.readFileSync(path.join(client, 'js/app.js'), 'utf8'), sandbox);
  const run = script => vm.runInContext(script, sandbox);
  const api = run('api');
  const toasts = [];
  sandbox.showToast = (message, type) => toasts.push({ message, type });
  api.getReflectionQueue = async () => ({ ok: true, queue: [], count: 0, total: 0, filtered_total: 0, offset: 0, has_more: false, next_batch_ids: [] });
  api.getMetaKnowledge = async () => ({ entries: [] });
  return { sandbox, run, api, elements, container, toasts };
}

function queued(id = 1) {
  return { id, experience_id: id + 100, priority: 0,
    queued_at: '2026-10-15T12:00:00Z', tools_used: ['create_reminder'],
    review: { user_query: 'Set a reminder tomorrow at noon.', source_label: 'Web' } };
}

function seed(h, count = 20) {
  h.run(`reflectionState.nextBatchIds = ${JSON.stringify(Array.from({ length: count }, (_, i) => i + 1))}; reflectionState.total = ${count};`);
}

function deferred() {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
}

const tick = () => new Promise(resolve => setImmediate(resolve));

test('queue rows escape stored text and show true paged/search counts beyond twenty', () => {
  const h = harness();
  const queue = Array.from({ length: 50 }, (_, i) => queued(i + 51));
  queue[0].review.user_query = '<img src=x onerror=alert(1)> & request';
  queue[0].review.source_label = '<script>source</script>';
  queue[0].timestamp = '2026-10-15T12:00:00Z';
  queue[0].timestamp_local_display = 'Configured local timestamp';
  h.run('reflectionState.total = 155; reflectionState.filteredTotal = 124; reflectionState.offset = 50; reflectionState.hasMore = true; reflectionState.query = "fan";');
  h.sandbox.renderReflectionPanel(queue, []);
  const html = h.container.innerHTML;
  assert.equal((html.match(/class="reflection-row"/g) || []).length, 50);
  assert.ok(html.includes('Showing 51–100 of 124 matching “fan” · 155 pending total'));
  assert.ok(html.includes('Priority 0.0'));
  assert.ok(html.includes('Configured local timestamp'));
  assert.ok(html.includes('&lt;img src=x onerror=alert(1)&gt; &amp; request'));
  assert.ok(!html.includes('<script>source'));
  assert.ok(html.includes('Process 20'));
  assert.ok(html.includes('☢️ Clear All'));
  assert.ok(html.includes('Batch controls use global queue priority, including while searching.'));
  assert.ok(html.includes('Open experience'));
  assert.ok(html.includes('title="Experience #151"'));
  assert.ok(!html.includes('Recorded success'));
  assert.ok(!html.includes('Earlier context'));
  assert.ok(html.includes('Discard and Clear All remove pending queue entries. Experiences and existing insights are kept.'));
});

test('a filtered empty page does not claim the whole pending queue is empty', () => {
  const h = harness();
  h.run('reflectionState.total = 90; reflectionState.filteredTotal = 0; reflectionState.query = "unmatched";');
  h.sandbox.renderReflectionPanel([], []);
  assert.ok(h.container.innerHTML.includes('No matching pending reflections'));
  assert.ok(h.container.innerHTML.includes('90 pending total'));
});

test('review loads only after opening and shows just the escaped request and recorded answer', async () => {
  const h = harness();
  let requests = 0;
  h.api.getReflectionReview = async (id, options) => {
    requests += 1;
    assert.equal(id, 1);
    assert.equal(options.mode, 'cloud');
    return { ok: true, item: { ...queued(), review: {
      user_query: 'User <img src=x> request', user_query_truncated: false,
      response: '<script>recorded answer</script>', response_truncated: false
    } } };
  };
  h.sandbox.renderReflectionPanel([queued()], []);
  assert.equal(requests, 0);
  const details = h.container.querySelectorAll('.reflection-review')[0];
  details.open = true;
  details.events.toggle();
  await tick();
  assert.equal(requests, 1);
  const html = details.body.innerHTML;
  assert.ok(html.includes('<h4>User request</h4>'));
  assert.ok(html.includes('<h4>Recorded answer</h4>'));
  assert.equal((html.match(/<h4>/g) || []).length, 2);
  assert.ok(html.includes('User &lt;img src=x&gt; request'));
  assert.ok(html.includes('&lt;script&gt;recorded answer&lt;/script&gt;'));
  assert.ok(!html.includes('<script>'));
  assert.ok(!html.includes('Excerpt shown.'));
  details.open = false; details.events.toggle();
  details.open = true; details.events.toggle();
  await tick();
  assert.equal(requests, 1);
});

test('complete recorded text stays readable without excerpt warnings', () => {
  const h = harness();
  const request = 'Compare the two options. '.repeat(60);
  const answer = 'The first costs $79 and the second costs $99. '.repeat(25);
  const html = h.sandbox.renderReflectionReview({ item: { review: {
    user_query: request, user_query_truncated: false,
    response: answer, response_truncated: false
  } } });
  assert.ok(html.includes(request));
  assert.ok(html.includes(answer));
  assert.ok(!html.includes('Excerpt shown.'));
  assert.equal((html.match(/<h4>/g) || []).length, 2);
});

test('request and answer excerpts are labeled independently, including saved truncation markers', () => {
  const h = harness();
  const result = { item: { review: {
    user_query: 'Saved request excerpt', user_query_truncated: true,
    response: 'Saved answer excerpt', response_truncated: true
  } } };
  const excerpts = h.sandbox.renderReflectionReview(result);
  assert.equal((excerpts.match(/Excerpt shown\./g) || []).length, 2);
  result.item.review.user_query_truncated = false;
  const answerOnly = h.sandbox.renderReflectionReview(result);
  assert.equal((answerOnly.match(/Excerpt shown\./g) || []).length, 1);
  result.item.review.response_truncated = false;
  result.item.review.response = 'Older recorded answer... [truncated]';
  const stored = h.sandbox.renderReflectionReview(result);
  assert.equal((stored.match(/Excerpt shown\./g) || []).length, 1);
});

test('missing request or answer has an explicit label', () => {
  const h = harness();
  const empty = h.sandbox.renderReflectionReview({ item: { review: {} } });
  assert.ok(empty.includes('The original request is not available.'));
  assert.ok(empty.includes('An answer was not recorded for this experience.'));
  const answer = h.sandbox.renderReflectionReview({ item: { review: { response: 'Reminder set for noon.' } } });
  assert.ok(answer.includes('Reminder set for noon.'));
  assert.ok(!answer.includes('An answer was not recorded'));
});

test('Open experience uses the existing experience modal entry point', () => {
  const h = harness();
  const calls = [];
  h.sandbox.viewExperience = id => calls.push(id);
  h.sandbox.renderReflectionPanel([queued(7)], []);
  const button = h.container.querySelectorAll('.reflection-experience')[0];
  button.events.click();
  assert.deepEqual(calls, [107]);
  assert.equal(button.attributes.title, 'Experience #107');
});

test('API requests carry a frozen mode and explicit queue IDs, without leaking request options', async () => {
  const h = harness();
  const calls = [];
  h.sandbox.fetch = async (url, options) => { calls.push({ url, options }); return { ok: true, json: async () => ({ ok: true }) }; };
  h.api.setMode('local');
  await h.api.triggerReflection(5, { mode: 'cloud', reflectionIds: [1, 2, 3, 4, 5] });
  assert.equal(calls[0].url, '/api/maintenance/reflect?batch_size=5&mode=cloud');
  assert.deepEqual(JSON.parse(calls[0].options.body), { reflection_ids: [1, 2, 3, 4, 5] });
  assert.ok(!('mode' in calls[0].options));
  await h.api.triggerReflection(1, { mode: 'local', reflectionId: 9 });
  assert.deepEqual(JSON.parse(calls[1].options.body), { reflection_id: 9 });
  // Exercise the shipped method rather than the fixture's default queue stub.
  await h.run('IntelligenceAPI.prototype.getReflectionQueue.call(api, {limit:50,offset:100,q:"fans & quiet"}, {mode:"cloud"})');
  assert.ok(calls[2].url.includes('offset=100&q=fans+%26+quiet&mode=cloud'));
});

test('Process 20 freezes global IDs, never retries failed entries and reports actual counts', async () => {
  const h = harness(); seed(h);
  const chunks = [];
  h.api.triggerReflection = async (size, options) => {
    chunks.push(Array.from(options.reflectionIds));
    assert.equal(options.mode, 'cloud');
    assert.equal(size, 5);
    h.run('reflectionState.nextBatchIds = [99,98,97,96,95];');
    return { ok: true, requested: 5, attempted: 5, processed: chunks.length === 1 ? 4 : 5, failed: chunks.length === 1 ? 1 : 0, skipped: 0 };
  };
  await h.sandbox.processReflections(20);
  assert.equal(chunks.length, 4);
  assert.deepEqual(chunks.flat(), Array.from({ length: 20 }, (_, i) => i + 1));
  assert.equal(new Set(chunks.flat()).size, 20);
  assert.ok(h.run('reflectionState.progress').includes('19 processed · 1 failed · 0 skipped · 20 attempted (20/20 entries checked)'));
  assert.equal(h.run('reflectionState.operation'), null);
});

test('Process one selects its row and blocks overlapping reflection/clear/modal-delete mutations', async () => {
  const h = harness(); seed(h);
  const pending = deferred();
  const calls = [];
  h.api.triggerReflection = (size, options) => { calls.push({ size, options }); return pending.promise; };
  h.api.deleteAllReflections = () => assert.fail('Overlapping clear reached the backend');
  h.api.deleteExperience = () => assert.fail('Overlapping full experience delete reached the backend');
  const processing = h.sandbox.processReflections(1, 17);
  await h.sandbox.processReflections(20);
  await h.sandbox.mutateReflectionQueue('clear');
  h.run('selectedExperienceId = 117;');
  await h.sandbox.deleteCurrentExperience();
  assert.equal(calls.length, 1);
  assert.equal(calls[0].size, 1);
  assert.equal(calls[0].options.reflectionId, 17);
  assert.equal(h.elements.get('deleteExperienceBtn').disabled, true);
  pending.resolve({ ok: true, requested: 1, attempted: 1, processed: 1, failed: 0, skipped: 0 });
  await processing;
});

test('Process one on an orphan reports a skipped entry and refreshes without an error', async () => {
  const h = harness(); seed(h);
  let refreshed = false;
  h.api.triggerReflection = async () => ({ ok: true, requested: 1, attempted: 0,
    processed: 0, failed: 0, skipped: 1,
    outcomes: [{ reflection_id: 17, status: 'skipped', reason: 'missing_experience' }] });
  h.api.getReflectionQueue = async () => {
    refreshed = true;
    return { ok: true, queue: [], total: 0, filtered_total: 0, next_batch_ids: [] };
  };
  await h.sandbox.processReflections(1, 17);
  assert.ok(refreshed);
  assert.ok(h.run('reflectionState.progress').includes('0 processed · 0 failed · 1 skipped · 0 attempted'));
  assert.ok(!h.toasts.some(toast => toast.type === 'error'));
});

test('Stop finishes the current chunk and does not launch another chunk', async () => {
  const h = harness(); seed(h);
  let calls = 0;
  h.api.triggerReflection = async () => {
    calls += 1;
    h.run('reflectionState.operation.stop = true;');
    return { ok: true, requested: 5, attempted: 4, processed: 3, failed: 1, skipped: 1 };
  };
  await h.sandbox.processReflections(20);
  assert.equal(calls, 1);
  assert.ok(h.run('reflectionState.progress').startsWith('Stopped. 3 processed · 1 failed · 1 skipped · 4 attempted (5/20 entries checked)'));
});

test('mode changes stop future chunks and old completions cannot overwrite the new panel', async () => {
  const h = harness(); seed(h);
  const pending = deferred();
  const calls = [];
  h.api.triggerReflection = (size, options) => { calls.push(options); return pending.promise; };
  const processing = h.sandbox.processReflections(20);
  h.run('resetReflectionState(); api.setMode("local");');
  assert.equal(calls[0].signal.aborted, true);
  assert.equal(h.elements.get('deleteExperienceBtn').disabled, false);
  h.container.innerHTML = '<p>New local queue</p>';
  pending.resolve({ ok: true, requested: 5, attempted: 5, processed: 5, failed: 0, skipped: 0 });
  await processing;
  assert.equal(calls.length, 1);
  assert.equal(calls[0].mode, 'cloud');
  assert.equal(h.container.innerHTML, '<p>New local queue</p>');
  assert.equal(h.toasts.length, 0);
});

test('new searches and mode changes reject stale queue responses even when fetch ignores abort', async () => {
  const h = harness();
  const first = deferred(); const second = deferred();
  let calls = 0; const signals = [];
  h.api.getReflectionQueue = (options, request) => { signals.push(request.signal); return ++calls === 1 ? first.promise : second.promise; };
  const old = h.sandbox.loadReflectionQueue({ query: 'old' });
  const latest = h.sandbox.loadReflectionQueue({ query: 'new', offset: 50 });
  const result = { queue: [queued(51)], total: 120, filtered_total: 60, count: 1, offset: 50, has_more: false, next_batch_ids: [1, 2] };
  second.resolve(result); await latest;
  assert.equal(signals[0].aborted, true);
  assert.ok(h.container.innerHTML.includes('Showing 51–51 of 60 matching “new”'));
  first.resolve({ ...result, queue: [queued(1)], offset: 0 }); await old;
  assert.ok(h.container.innerHTML.includes('Showing 51–51 of 60 matching “new”'));
  const late = deferred(); h.api.getReflectionQueue = () => late.promise;
  const cloud = h.sandbox.loadReflectionQueue();
  h.run('resetReflectionState(); api.setMode("local");');
  h.container.innerHTML = 'Local queue';
  late.resolve(result); await cloud;
  assert.equal(h.container.innerHTML, 'Local queue');
});

test('transport failure stops further chunks without claiming unconfirmed processing succeeded', async () => {
  const h = harness(); seed(h);
  let calls = 0;
  h.api.triggerReflection = async () => { calls += 1; throw new Error('Connection lost'); };
  await h.sandbox.processReflections(20);
  assert.equal(calls, 1);
  assert.ok(h.run('reflectionState.progress').includes('0 processed'));
  assert.ok(h.run('reflectionState.progress').includes('current request may already have completed'));
  assert.equal(h.run('reflectionState.operation'), null);
});

test('discard/clear retain experiences, while explicit experience deletion refreshes the reflection queue', async () => {
  const h = harness(); seed(h);
  const calls = []; const confirmations = [];
  h.sandbox.confirm = message => { confirmations.push(message); return true; };
  h.api.deleteReflection = async (id, options) => { calls.push(['discard', id, options.mode]); return { ok: true }; };
  h.api.deleteAllReflections = async options => { calls.push(['clear', options.mode]); return { ok: true, deleted: 20 }; };
  h.api.deleteExperience = async (id, options) => { calls.push(['experience', id, options.mode]); return { ok: true }; };
  let refreshes = 0;
  h.api.getReflectionQueue = async () => { refreshes += 1; return { queue: [], total: 0, filtered_total: 0, count: 0, offset: 0, next_batch_ids: [] }; };
  h.sandbox.loadAllExperiencesForCounts = async () => {};
  h.sandbox.loadExperiences = async () => {};
  h.sandbox.closeAllModals = () => {};
  await h.sandbox.mutateReflectionQueue('discard', 1);
  await h.sandbox.mutateReflectionQueue('clear');
  h.run('selectedExperienceId = 101;');
  await h.sandbox.deleteCurrentExperience();
  assert.deepEqual(calls, [['discard', 1, 'cloud'], ['clear', 'cloud'], ['experience', 101, 'cloud']]);
  assert.equal(refreshes, 3);
  assert.ok(confirmations[0].includes('experience and existing insights will be kept'));
  assert.ok(confirmations[1].includes('pending reflections in cloud'));
  assert.ok(confirmations[1].includes('Experiences and existing insights will be kept'));
});

test('queue layout keeps keyboard focus, two-line headlines and narrow/touch rules', () => {
  const css = fs.readFileSync(path.join(client, 'css/intelligence.css'), 'utf8');
  assert.ok(css.includes('-webkit-line-clamp: 2'));
  assert.ok(css.includes('.reflection-layout :is(button, summary):focus-visible'));
  assert.ok(css.includes('@media (max-width: 480px)'));
  assert.ok(css.includes('@media (pointer: coarse)'));
  assert.ok(css.includes('min-height: 44px'));
});
