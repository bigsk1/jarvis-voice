"""Canvas links in rendered answers follow the same browser origin as their preview."""

import json

import pytest
from test_web_assistant_message_rendering import run_message_browser

LINK_DOM = r"""
vm.runInContext(fs.readFileSync(clientPath + '/vendor/marked.min.js', 'utf8'), sandbox,
  {filename: 'marked.min.js'});
assert.equal(typeof sandbox.marked.parse, 'function');

const decode = value => String(value).replace(/&(?:amp|quot|#39|lt|gt);/g,
  entity => ({'&amp;':'&', '&quot;':'"', '&#39;':"'", '&lt;':'<', '&gt;':'>'}[entity]));
function attributes(tag) {
  return Object.fromEntries([...tag.matchAll(/([\w-]+)\s*=\s*(?:"([^"]*)"|'([^']*)')/g)]
    .map(match => [match[1], decode(match[2] ?? match[3])]));
}
class MarkdownAnchor extends Element {
  constructor(attrs, content, ancestors) {
    super();
    this.attrs = attrs;
    this.className = attrs.class || '';
    this._text = decode(content.replace(/<[^>]*>/g, ''));
    this.ancestors = ancestors;
  }
  getAttribute(name) { return this.attrs[name] ?? null; }
  setAttribute(name, value) { this.attrs[name] = String(value); }
  closest(selector) {
    const tags = selector.split(',').map(value => value.trim().toLowerCase());
    return this.ancestors.find(parent => tags.includes(parent.tag)) || null;
  }
}
class MarkdownMessage extends Element {
  set innerHTML(value) {
    super.innerHTML = value;
    this.anchors = [];
    const ancestors = [];
    // Parse only generated tags/quoted attributes needed for link selection.
    // Markdown itself, preview selection and navigation remain shipped code.
    for (const match of value.matchAll(/<(\/?)([a-z][\w-]*)\b[^>]*>/gi)) {
      const tag = match[2].toLowerCase();
      if (match[1]) {
        const index = ancestors.findLastIndex(parent => parent.tag === tag);
        if (index >= 0) ancestors.splice(index);
        continue;
      }
      const attrs = attributes(match[0]);
      if (tag === 'a') {
        const end = value.indexOf('</a>', match.index);
        const anchor = new MarkdownAnchor(attrs,
          value.slice(match.index + match[0].length, end), ancestors.slice());
        anchor.inBubble = ancestors.some(parent => parent.classes.includes('message-bubble'));
        this.anchors.push(anchor);
      }
      if (!['img', 'br', 'hr', 'input', 'source', 'meta', 'link'].includes(tag)) {
        ancestors.push({tag, classes: (attrs.class || '').split(/\s+/)});
      }
    }
  }
  get innerHTML() { return super.innerHTML; }
  querySelectorAll(selector) {
    if (selector === '.message-bubble a.content-link') {
      return this.anchors.filter(anchor => anchor.inBubble
        && anchor.classList.contains('content-link'));
    }
    return super.querySelectorAll(selector);
  }
}
sandbox.document.createElement = () => new MarkdownMessage();

function navigation(webOrigin, configuration) {
  const web = new URL(webOrigin);
  sandbox.window.location = {origin: web.origin, hostname: web.hostname, href: web.href};
  sandbox.window.__jarvisUINavigationConfig = configuration;
  vm.runInContext(fs.readFileSync(ROOT + '/lib/static/ui-navigation.js', 'utf8'), sandbox,
    {filename: 'ui-navigation.js'});
}
function byLabel(ui, label) {
  const anchor = message(ui).anchors.find(item => item.textContent === label);
  assert.ok(anchor, 'Missing rendered link: ' + label);
  return anchor;
}
"""


@pytest.mark.parametrize("live", [True, False], ids=["live", "history"])
def test_canvas_markdown_and_preview_follow_host_scoped_navigation(live):
    run_message_browser(f"const live = {json.dumps(live)};\n" + LINK_DOM + r"""
const path = '/page_canvas_links';
for (const scenario of [
  {web:'https://assistant.demo-tail.example:7443', host:'assistant.demo-tail.example',
   source:'http://127.0.0.1:8890', destination:'https://assistant.demo-tail.example:9443'},
  {web:'https://jarvis.example.test:5443', host:'jarvis.example.test',
   source:'http://192.0.2.42:8890', destination:'https://canvas.example.test:10443'},
  {web:'http://192.0.2.42:5001', host:'192.0.2.42',
   source:'http://localhost:8890', destination:'http://192.0.2.42:8890'},
  {web:'http://localhost:5001', host:'localhost',
   source:'http://192.0.2.42:8890', destination:'http://localhost:8899'},
  {web:'https://assistant.demo-tail.example', source:'http://192.0.2.42:8890'},
  {web:'https://assistant.demo-tail.example', host:'different-host.example',
   source:'http://192.0.2.42:8890', destination:'https://unused.example:9443'},
]) {
  navigation(scenario.web, scenario.host
    ? {hostname:scenario.host, urls:{canvas:scenario.destination}} : {});
  const expectedOrigin = scenario.host === new URL(scenario.web).hostname
    ? scenario.destination : scenario.source;
  const source = scenario.source + path + '?from=tool#card';
  const narrative = scenario.source + path + '?view=full&lang=en#summary';
  const payload = {canvas:{page_id:'page_canvas_links', title:'Canvas note', url:source}};
  const original = JSON.stringify(payload);
  const text = source + '\n\n[Read the note](' + narrative + ')';
  const ui = chat();
  render(ui, text, ['canvas'], payload, live, {fromHistory:!live});
  const preview = ui._extractCanvasPreview(payload);
  assert.equal(preview.sourceUrl, source);
  assert.equal(preview.url, expectedOrigin + path + '?from=tool#card');
  const links = message(ui).querySelectorAll('.message-bubble a.content-link');
  assert.equal(links.length, 2);
  assert.equal(links[0].getAttribute('href'), expectedOrigin + path + '?from=tool#card');
  assert.equal(links[0].textContent, expectedOrigin + path + '?from=tool#card');
  assert.equal(byLabel(ui, 'Read the note').getAttribute('href'),
    expectedOrigin + path + '?view=full&lang=en#summary');
  assert.ok(message(ui).innerHTML.includes('href="' + preview.url + '"'));
  assert.equal(JSON.stringify(payload), original);
  assert.equal(effects.filter(effect => Array.isArray(effect) && effect[0] === 'actions').at(-1)[1], text);
}
""")


@pytest.mark.parametrize("live", [True, False], ids=["live", "history"])
def test_canvas_rewrite_preserves_unrelated_links_code_labels_and_saved_payload(live):
    run_message_browser(f"const live = {json.dumps(live)};\n" + LINK_DOM + r"""
const source = 'http://127.0.0.1:8890/page_canvas_links';
const destination = 'https://assistant.demo-tail.example:9443';
navigation('https://assistant.demo-tail.example:7443',
  {hostname:'assistant.demo-tail.example', urls:{canvas:destination}});
const unchanged = [
  ['Another Canvas page', 'http://127.0.0.1:8890/page_other'],
  ['External page', 'https://external.example.test/page_canvas_links'],
  ['Different protocol', 'https://127.0.0.1:8890/page_canvas_links'],
  ['Different port', 'http://127.0.0.1:8891/page_canvas_links'],
  ['Credential-bearing link', 'http://reader:example-password@127.0.0.1:8890/page_canvas_links'],
  ['Email', 'mailto:reader@example.test'],
  ['Local file', 'file:///tmp/page_canvas_links'],
];
const text = [
  '[Open the report](' + source + '?display=full&language=en#sources)',
  ...unchanged.map(([label, href]) => '[' + label + '](' + href + ')'),
  '`' + source + '`',
  '```text\n' + source + '\n```',
  '<pre><a class="content-link" href="' + source + '">Preformatted link</a></pre>',
  '<code><a class="content-link" href="' + source + '">Code link</a></code>',
  '<a class="other-link" href="' + source + '">Unrelated styled link</a>',
].join('\n\n');
const payload = {canvas:{page_id:'page_canvas_links', title:'Canvas note', url:source,
  content:text, source_query:'Keep the stored URL: ' + source}};
const before = JSON.stringify(payload);
const ui = chat();
render(ui, text, ['canvas'], payload, live, {fromHistory:!live});
assert.equal(byLabel(ui, 'Open the report').getAttribute('href'),
  destination + '/page_canvas_links?display=full&language=en#sources');
for (const [label, href] of unchanged) assert.equal(byLabel(ui, label).getAttribute('href'), href);
for (const label of ['Preformatted link', 'Code link', 'Unrelated styled link']) {
  assert.equal(byLabel(ui, label).getAttribute('href'), source);
}
assert.ok(message(ui).innerHTML.includes('<code>' + source + '</code>'));
assert.ok(message(ui).innerHTML.includes('<pre><code'));
assert.equal(JSON.stringify(payload), before);
""")


@pytest.mark.parametrize("live", [True, False], ids=["live", "history"])
def test_canvas_mapping_requires_a_valid_structured_result(live):
    run_message_browser(f"const live = {json.dumps(live)};\n" + LINK_DOM + r"""
const source = 'http://127.0.0.1:8890/page_canvas_links';
const destination = 'https://assistant.demo-tail.example:9443';
for (const [tools, payload, configuredDestination] of [
  [[], {}, destination],
  [['canvas'], {canvas:{title:'Missing page id', url:source}}, destination],
  [['canvas'], {canvas:{page_id:'page_canvas_links', url:'file:///tmp/page_canvas_links'}}, destination],
  [['canvas'], {canvas:{page_id:'page_canvas_links', url:'http://%'}}, destination],
  [['canvas'], {canvas:{page_id:'page_canvas_links', url:'http://reader:example-password@127.0.0.1:8890/page_canvas_links'}}, destination],
  [['canvas'], {canvas:{page_id:'page_canvas_links', url:source}}, 'javascript:alert(1)'],
  [['canvas'], {canvas:{page_id:'page_canvas_links', url:source}}, 'https://reader:example-password@canvas.example.test'],
]) {
  navigation('https://assistant.demo-tail.example:7443',
    {hostname:'assistant.demo-tail.example', urls:{canvas:configuredDestination}});
  const before = JSON.stringify(payload);
  const ui = chat();
  render(ui, '[Original URL](' + source + ')', tools, payload, live, {fromHistory:!live});
  assert.equal(byLabel(ui, 'Original URL').getAttribute('href'), source);
  assert.equal(JSON.stringify(payload), before);
}
""")
