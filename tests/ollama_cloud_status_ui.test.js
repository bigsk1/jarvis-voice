/** Exercise the shipped lazy account card without a server or provider calls. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');
class Element {
  constructor(tag = 'span') {
    this.tag = tag;
    this.children = [];
    this._text = '';
    this.title = '';
  }
  set textContent(text) { this._text = text; this.children = []; }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
  appendChild(child) { this.children.push(child); }
  replaceChildren(...children) { this._text = ''; this.children = children; }
  set innerHTML(_) { throw new Error('Account content must use DOM text'); }
}

function setup() {
  const elements = {'ollama-cloud-status': new Element()};
  const calls = [], pending = [], timers = new Map(), applied = [];
  let timerId = 0;
  const sandbox = {
    window: {}, URL, AbortController,
    setTimeout(callback, timeout) {
      assert.equal(timeout, 30000);
      const id = ++timerId;
      timers.set(id, callback);
      return id;
    },
    clearTimeout(id) { timers.delete(id); },
    document: {
      getElementById: id => elements[id],
      createElement: tag => new Element(tag),
      createTextNode: text => ({textContent: text})
    },
    Utils: {auth: {fetch(url, options) {
      calls.push({url, options});
      assert.ok(options.signal, 'Every account request must have a timeout');
      return new Promise((resolve, reject) => pending.push({resolve, reject}));
    }}}
  };
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(path.join(root, 'jarvis-web/client/js/ollama-cloud-status.js'), 'utf8'), sandbox);
  const app = {
    socket: {mode: 'cloud'},
    _settingsData: {mode: 'cloud', provider_availability: {
      llm: {ollama: {status: 'unknown', reason: null}},
      completion_guard: {ollama: {status: 'unknown', reason: null}}
    }},
    _applyProviderAvailability(...args) { applied.push(args); }
  };
  const card = new sandbox.window.OllamaCloudStatus(app);
  return {card, app, elements, calls, pending, timers, applied};
}

const response = data => ({ok: true, status: 200, json: async () => data});
const account = extra => ({
  reachable: true, signed_in: true, connection_mode: 'signed_in_host', plan: 'pro',
  balance: {status: 'unsupported', data: null}, usage: {status: 'unsupported', data: null},
  dashboard_url: 'https://ollama.com/settings', checked_at: '2026-10-22T16:00:00Z', ...extra
});
const text = state => state.elements['ollama-cloud-status'].textContent;

test('card is lazy, authenticated, mode scoped and bounded; shipped helper precedes app', async () => {
  const state = setup();
  assert.equal(state.calls.length, 0);
  state.app._settingsData.mode = 'local';
  await state.card.load();
  assert.equal(state.calls.length, 0);
  state.app._settingsData.mode = 'cloud';
  const load = state.card.load();
  assert.equal(state.calls[0].url, '/api/ollama/cloud-status?mode=cloud');
  assert.equal(state.calls[0].options.method, undefined);
  state.pending.shift().resolve(response(account())); await load;
  assert.equal(state.timers.size, 0);
  assert.match(text(state), /Signed in · pro/);
  assert.equal(state.app._settingsData.provider_availability.llm.ollama.status, 'available');

  const html = fs.readFileSync(path.join(root, 'jarvis-web/client/index.html'), 'utf8');
  const source = '/js/ollama-cloud-status.js';
  assert.equal(html.split(source).length, 2);
  assert.ok(html.indexOf(source) < html.indexOf('/js/app.js'));
  assert.match(fs.readFileSync(path.join(root, 'jarvis-web/client/js/app.js'), 'utf8'), /new window\.OllamaCloudStatus\(this\)/);
});

test('monthly included allowance, purchased credits, resets and usage totals stay distinct', async () => {
  const state = setup();
  const load = state.card.load();
  state.pending.shift().resolve(response(account({connection_mode: 'api_key', balance: {
    status: 'available', data: {included: {balance_usd: 0, allowance_usd: 100,
      period: {from: '2026-10-01T00:00:00Z', until: '2026-11-01T00:00:00Z'}}, purchased: {balance_usd: 25}}
  }, usage: {status: 'available', data: {range: '7d', scope: 'self', totals: {
    request_count: 15, usage_usd: 0.01718, input_tokens: 106000, cached_input_tokens: 46000, output_tokens: 13600
  }}}}))); await load;
  const content = text(state);
  assert.match(content, /API key verified/);
  assert.match(content, /Included: \$0\.00 remaining of \$100\.00/);
  assert.match(content, /Purchased: \$25\.00 remaining/);
  assert.match(content, /Included credits renew:/);
  assert.match(content, /Last 7 days: 15 requests · \$0\.01718 usage/);
  assert.match(content, /106,000 input · 46,000 cached input · 13,600 output/);
  assert.match(content, /Usage reporting may be delayed/);
  assert.doesNotMatch(content, /exhausted|unavailable/);
  assert.equal(state.app._settingsData.provider_availability.llm.ollama.status, 'available');
});

test('legacy percentages mean remaining and absent spend or token metrics are never invented', async () => {
  const state = setup();
  const load = state.card.load();
  state.pending.shift().resolve(response(account({balance: {status: 'available', data: {
    included: {session: {remaining_percent: 75, resets_at: '2026-10-23T09:30:00Z'}, weekly: {remaining_percent: 40}},
    purchased: {balance_usd: 0}
  }}, usage: {status: 'available', data: {range: '7d', scope: 'self', totals: {request_count: 0}}}}))); await load;
  assert.match(text(state), /Session: 75% remaining · resets/);
  assert.match(text(state), /Weekly: 40% remaining/);
  assert.match(text(state), /Purchased: \$0\.00 remaining/);
  assert.match(text(state), /Last 7 days: 0 requests/);
  assert.doesNotMatch(text(state), /Tokens|\$0\.00 usage|25% remaining|60% remaining/);
});

test('partial failures preserve the successful half and unknown auth does not disable the provider', async () => {
  const state = setup();
  let load = state.card.load();
  state.pending.shift().resolve(response(account({signed_in: 'unknown',
    balance: {status: 'rate_limited', data: null},
    usage: {status: 'available', data: {totals: {request_count: 12}}}}))); await load;
  assert.match(text(state), /Account status unavailable/);
  assert.match(text(state), /Balance: temporarily rate limited/);
  assert.match(text(state), /Last 7 days: 12 requests/);
  assert.equal(state.app._settingsData.provider_availability.llm.ollama.status, 'unknown');
  assert.equal(state.applied.length, 0);
  load = state.card.load();
  state.pending.shift().resolve(response(account({balance: {status: 'available', data: {
    included: {session: {remaining_percent: 87}}
  }}, usage: {status: 'unavailable', data: null}}))); await load;
  assert.match(text(state), /Session: 87% remaining/);
  assert.match(text(state), /7-day usage: unavailable/);
  assert.equal(state.app._settingsData.provider_availability.llm.ollama.status, 'available');
});

test('old daemons retain dashboard access without confusing unsupported usage with sign-out', async () => {
  const state = setup();
  const load = state.card.load();
  state.pending.shift().resolve(response(account({signed_in: 'unknown', plan: null}))); await load;
  assert.match(text(state), /Balance: not supported by this host/);
  assert.match(text(state), /7-day usage: not supported by this host/);
  assert.doesNotMatch(text(state), /Not signed in|API key rejected/);
  const link = state.elements['ollama-cloud-status'].children[1].children[0].children.at(-1);
  assert.equal(link.href, 'https://ollama.com/settings');
  assert.equal(link.rel, 'noopener noreferrer');
  assert.equal(state.applied.length, 0);
});

test('only a confirmed auth rejection disables provider choices', async () => {
  const state = setup();
  const load = state.card.load();
  state.pending.shift().resolve(response(account({signed_in: false, connection_mode: 'api_key'})));
  await load;
  for (const domain of ['llm', 'completion_guard']) {
    assert.equal(state.app._settingsData.provider_availability[domain].ollama.status, 'unavailable');
  }
});

test('account endpoint transport failures preserve inference provider choices', async () => {
  for (const connection_mode of ['api_key', 'signed_in_host']) {
    const state = setup();
    state.app._settingsData.provider_availability.llm.ollama.status = 'available';
    const load = state.card.load();
    state.pending.shift().resolve(response(account({reachable: false, signed_in: 'unknown', connection_mode})));
    await load;
    assert.equal(state.app._settingsData.provider_availability.llm.ollama.status, 'available');
    assert.equal(state.applied.length, 0);
    assert.match(text(state), /Account service unreachable/);
  }
});

test('mode changes, replaced cards and superseding requests cannot mutate current UI or availability', async () => {
  for (const transition of ['mode', 'card', 'settings']) {
    const state = setup();
    const old = state.card.load();
    if (transition === 'mode') state.app._settingsData.mode = 'local';
    if (transition === 'card') state.elements['ollama-cloud-status'] = new Element();
    if (transition === 'settings') state.app._settingsData = {...state.app._settingsData};
    state.pending.shift().resolve(response(account({signed_in: false}))); await old;
    assert.equal(text(state), '');
    assert.equal(state.applied.length, 0);
  }
  const state = setup();
  const old = state.card.load();
  const oldResponse = state.pending.shift();
  const newer = state.card.load();
  assert.equal(state.calls[0].options.signal.aborted, true);
  state.pending.shift().resolve(response(account({plan: 'new'}))); await newer;
  oldResponse.reject(new Error('private credential')); await old;
  assert.match(text(state), /new/);
  assert.doesNotMatch(text(state), /private/);
});

test('untrusted account text and links cannot create HTML, and bad numbers stay unknown', async () => {
  const state = setup();
  const load = state.card.load();
  state.pending.shift().resolve(response(account({signed_in: false, plan: '<img src=x onerror=unsafe()>',
    signin_url: 'javascript:unsafe()', dashboard_url: 'https://ollama.com.attacker.test/settings',
    balance: {status: 'available', data: {included: {balance_usd: null, allowance_usd: false,
      session: {remaining_percent: NaN}, weekly: {remaining_percent: 150}}, purchased: {balance_usd: -1}}},
    usage: {status: 'available', data: {totals: {request_count: null, usage_usd: false, input_tokens: -1}}}
  }))); await load;
  assert.match(text(state), /<img src=x onerror=unsafe\(\)>/);
  assert.match(text(state), /Balance: unavailable/);
  assert.match(text(state), /7-day usage: unavailable/);
  assert.doesNotMatch(text(state), /\$0|NaN|150%|-1/);
  const link = state.elements['ollama-cloud-status'].children[1].children[0].children.at(-1);
  assert.equal(link.href, 'https://ollama.com/settings');
  for (const unsafe of ['https://name:secret@ollama.com/a', 'https://ollama.com:8443/a', 'http://ollama.com/a']) {
    assert.equal(state.card.accountLink(unsafe), null);
  }
  assert.equal(state.card.accountLink('https://ollama.com/signin/example'), 'https://ollama.com/signin/example');
});

test('timeouts and HTTP errors show a generic failure, clear timers and leave provider state alone', async () => {
  const state = setup();
  let load = state.card.load();
  const [expire] = state.timers.values();
  expire();
  assert.equal(state.calls[0].options.signal.aborted, true);
  state.pending.shift().reject(new Error('private account payload')); await load;
  assert.equal(text(state), 'Ollama CloudAccount status unavailable');
  assert.equal(state.timers.size, 0);
  assert.equal(state.applied.length, 0);
  load = state.card.load();
  state.pending.shift().resolve({ok: false, status: 503, json: async () => { throw new Error('must not read raw errors'); }});
  await load;
  assert.equal(text(state), 'Ollama CloudAccount status unavailable');
  assert.equal(state.applied.length, 0);
});
