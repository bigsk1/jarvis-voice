import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { DraftBuffer, canSend, inlineParts, isRunActive, messageBlocks, safeLinkUrl, safePreviewUrl } from '../ui/view-model.js';
import { renderMessageContent, renderMessage } from '../ui/render.js';

// Deliberately has no innerHTML API: renderer output must consist of DOM nodes.
class Node {
  constructor(tag = '') { this.tagName = tag; this.children = []; this.attributes = {}; this.dataset = {}; }
  append(...nodes) { this.children.push(...nodes.flatMap(node => node.tagName === '#fragment' ? node.children : [node])); }
  set textContent(value) { this.children = []; this.text = String(value); }
  get textContent() { return (this.text || '') + this.children.map(node => typeof node === 'string' ? node : node.textContent).join(''); }
  setAttribute(name, value) { this.attributes[name] = value; }
}
const document = {
  createElement: tag => new Node(tag),
  createTextNode: text => { const node = new Node('#text'); node.textContent = text; return node; },
  createDocumentFragment: () => new Node('#fragment'),
};
function descendants(node) { return [node, ...node.children.flatMap(child => typeof child === 'object' ? descendants(child) : [])]; }

test('provider HTML and unsafe Markdown URLs remain inert text', () => {
  const payload = '<img src=x onerror="alert(1)"> [run](javascript:alert) [data](data:text/html,bad) **result**';
  const rendered = renderMessageContent(document, payload);
  const nodes = descendants(rendered);
  assert.equal(nodes.some(node => ['img', 'script', 'a'].includes(node.tagName)), false);
  assert.ok(rendered.textContent.includes('<img src=x onerror="alert(1)">'));
  assert.ok(rendered.textContent.includes('[run](javascript:alert)'));
  assert.equal(nodes.find(node => node.tagName === 'strong').textContent, 'result');
});

test('valid source links open separately without an opener; code never becomes HTML', () => {
  const rendered = renderMessageContent(document, 'See [source](https://example.test/a?q=1).\n\n```html\n<script>bad()</script>\n```');
  const nodes = descendants(rendered);
  const link = nodes.find(node => node.tagName === 'a');
  assert.equal(link.href, 'https://example.test/a?q=1');
  assert.equal(link.target, '_blank');
  assert.equal(link.rel, 'noopener noreferrer');
  assert.equal(nodes.find(node => node.tagName === 'code').textContent, '<script>bad()</script>');
  assert.equal(nodes.some(node => node.tagName === 'script'), false);
});

test('previews only accept raster data, never direct server requests or SVG', () => {
  assert.equal(safePreviewUrl('data:image/png;base64,aGVsbG8='), 'data:image/png;base64,aGVsbG8=');
  for (const value of ['https://jarvis.test/api/uploads/file.png', '/api/uploads/file.png', 'data:image/svg+xml;base64,aGVsbG8=', 'javascript:alert(1)', 'blob:https://evil.test/123']) assert.equal(safePreviewUrl(value), null);
  const rendered = renderMessage(document, { role: 'user', content: 'Look at this', attachments: [{ previewUrl: 'https://jarvis.test/private.png', label: 'Screenshot / image' }] });
  assert.equal(descendants(rendered).some(node => node.tagName === 'img'), false);
  assert.ok(rendered.textContent.includes('Screenshot / image'));
});

test('only HTTP(S) navigation is allowed and incomplete code fences remain readable', () => {
  for (const value of ['javascript:alert(1)', 'file:///etc/passwd', 'moz-extension://test/private', 'data:text/html,x']) assert.equal(safeLinkUrl(value), null);
  assert.equal(safeLinkUrl('https://example.test/path'), 'https://example.test/path');
  assert.deepEqual(messageBlocks('Before\n```sh\necho hello'), [{ type: 'text', text: 'Before\n' }, { type: 'code', language: 'sh', text: 'echo hello' }]);
  assert.ok(inlineParts('[x](javascript:bad)').every(part => part.type === 'text'));
});

test('send is disabled during reconnect recovery and active work, including unknown statuses', () => {
  const state = { connection: { status: 'connected' }, draft: {} };
  assert.equal(canSend(state, 'Hello'), true);
  assert.equal(canSend(state, '  '), false);
  assert.equal(canSend({ ...state, draft: { attachment: {} } }, ''), true);
  assert.equal(canSend({ ...state, draft: { context: {} } }, ''), true);
  for (const status of ['running', 'sending', 'stopping', 'recovering', 'new-server-state']) {
    assert.equal(canSend({ ...state, run: { status } }, 'Hello'), false);
  }
  assert.equal(isRunActive({ connection: { status: 'recovering' }, run: null }), true);
  assert.equal(canSend({ ...state, run: { status: 'completed' } }, 'Hello'), true);
  assert.equal(canSend({ ...state, pendingMode: 'local' }, 'Hello'), false);
});

test('drafts survive progress updates, delayed acknowledgments and typing during Send', () => {
  const draft = new DraftBuffer();
  draft.accept('Previous draft');
  draft.edit('Why did this fail?');
  assert.equal(draft.accept('Previous draft'), 'Why did this fail?');
  draft.edit('Why did this fail? More detail.');
  assert.equal(draft.accept('Why did this fail?'), 'Why did this fail? More detail.');
  draft.accept(draft.value);
  assert.equal(draft.dirty, false);
  draft.edit('My next question');
  assert.equal(draft.sent('Why did this fail? More detail.'), 'My next question');
  assert.equal(draft.sent('My next question'), '');
  draft.edit('Unsent');
  assert.equal(draft.accept('', true), '');
});

test('the panel is standalone, contains no inline script, and its referenced controls exist', async () => {
  const html = await readFile(new URL('../ui/panel.html', import.meta.url), 'utf8');
  const js = await readFile(new URL('../ui/panel.js', import.meta.url), 'utf8');
  assert.doesNotMatch(html, /\son\w+\s*=|<script(?![^>]*\bsrc=)/i);
  assert.doesNotMatch(html, /(?:src|href)=["']https?:/i);
  assert.doesNotMatch(js, /\b(?:fetch|XMLHttpRequest|WebSocket)\s*\(|\.innerHTML\s*=|\beval\s*\(/);
  const ids = new Set([...html.matchAll(/\bid="([^"]+)"/g)].map(match => match[1]));
  for (const [, id] of js.matchAll(/\$\('([^']+)'\)/g)) assert.ok(ids.has(id), `Missing panel element: ${id}`);
});
