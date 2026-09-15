import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { DraftBuffer, canSend, imageContextHint, inlineParts, isRunActive, messageBlocks, notificationPreferences, safeLinkUrl, safePreviewUrl } from '../ui/view-model.js';
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

test('assistant sections and action lists render as headings and list items', () => {
  const rendered = renderMessageContent(document, [
    '## Image analysis',
    'The image shows a software settings panel.',
    '### Details',
    '- **Subject:** a settings panel',
    '- The `Save` button is visible.',
    '',
    '### Next steps ###',
    '1. Review [the guide](https://example.test/guide).',
    '2. Save your changes.',
  ].join('\n'));
  assert.deepEqual(rendered.children.map(node => node.tagName), ['h2', 'p', 'h3', 'ul', 'h3', 'ol']);
  assert.equal(rendered.children[0].textContent, 'Image analysis');
  assert.equal(rendered.children[4].textContent, 'Next steps');
  const bullets = rendered.children[3];
  assert.deepEqual(bullets.children.map(node => node.tagName), ['li', 'li']);
  assert.deepEqual(bullets.children.map(node => node.textContent), ['Subject: a settings panel', 'The Save button is visible.']);
  const nodes = descendants(rendered);
  assert.equal(nodes.find(node => node.tagName === 'strong').textContent, 'Subject:');
  assert.equal(nodes.find(node => node.tagName === 'code').textContent, 'Save');
  assert.equal(nodes.find(node => node.tagName === 'a').href, 'https://example.test/guide');
  assert.equal(rendered.children[5].start, 1);
});

test('numbered lists preserve their start, nesting and indented continuation text', () => {
  const rendered = renderMessageContent(document, [
    '3. First step',
    '   with a continuation.',
    '   - Nested point',
    '   - Another point',
    '',
    '4. Second step',
    '   ```sh',
    '   ## literal code',
    '   - also code',
    '   ```',
    '',
    'After the list.',
  ].join('\n'));
  assert.deepEqual(rendered.children.map(node => node.tagName), ['ol', 'p']);
  const list = rendered.children[0];
  assert.equal(list.start, 3);
  assert.equal(list.children.length, 2);
  assert.deepEqual(list.children[0].children.map(node => node.tagName), ['p', 'ul']);
  assert.equal(list.children[0].children[0].textContent, 'First step\nwith a continuation.');
  assert.deepEqual(list.children[0].children[1].children.map(node => node.textContent), ['Nested point', 'Another point']);
  assert.equal(descendants(list.children[1]).find(node => node.tagName === 'code').textContent, '## literal code\n- also code');
  assert.equal(rendered.children[1].textContent, 'After the list.');
});

test('headings and lists keep HTML inert and never load Markdown images', () => {
  const rendered = renderMessageContent(document, [
    '## <img src=x onerror="alert(1)">',
    '- <script>bad()</script>',
    '- [run](javascript:alert)',
    '- ![remote image](https://example.test/private.png)',
    '### **Safe text** and `code`',
  ].join('\n'));
  const nodes = descendants(rendered);
  assert.equal(nodes.some(node => ['img', 'script', 'iframe'].includes(node.tagName)), false);
  assert.equal(rendered.children[0].textContent, '<img src=x onerror="alert(1)">');
  assert.ok(rendered.textContent.includes('<script>bad()</script>'));
  assert.ok(rendered.textContent.includes('[run](javascript:alert)'));
  assert.equal(nodes.filter(node => node.tagName === 'a').length, 1);
  assert.equal(nodes.find(node => node.tagName === 'a').rel, 'noopener noreferrer');
  assert.equal(nodes.find(node => node.tagName === 'strong').textContent, 'Safe text');
});

test('fences protect Markdown syntax and ordinary or escaped markers remain text', () => {
  const rendered = renderMessageContent(document, [
    '#No heading',
    '####### Too many hashes',
    '\\## Escaped heading',
    '\\- Escaped bullet',
    '1.5 is a number',
    '',
    '```markdown',
    '## Code heading',
    '- Code bullet',
    '1. Code item',
    '<b>literal</b>',
    '```',
    '### Real heading',
    '* Asterisk bullet',
    '+ Plus bullet',
    '2) Numbered item',
  ].join('\r\n'));
  assert.deepEqual(rendered.children.map(node => node.tagName), ['p', 'div', 'h3', 'ul', 'ol']);
  assert.ok(rendered.children[0].textContent.includes('\\## Escaped heading'));
  const code = descendants(rendered.children[1]).find(node => node.tagName === 'code');
  assert.equal(code.textContent, '## Code heading\n- Code bullet\n1. Code item\n<b>literal</b>');
  assert.deepEqual(rendered.children[3].children.map(node => node.textContent), ['Asterisk bullet', 'Plus bullet']);
  assert.equal(rendered.children[4].start, 2);
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
  assert.deepEqual(messageBlocks('Before\n```sh\necho hello'), [{ type: 'text', text: 'Before' }, { type: 'code', language: 'sh', text: 'echo hello' }]);
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

test('notification preferences default to badges with private desktop previews off', () => {
  assert.deepEqual(notificationPreferences(), {showBadge: true, desktopNotifications: false, notificationPreview: false});
  assert.deepEqual(notificationPreferences({showBadge: false, desktopNotifications: true, notificationPreview: true}),
    {showBadge: false, desktopNotifications: true, notificationPreview: true});
  assert.deepEqual(notificationPreferences({showBadge: 'false', desktopNotifications: 'true', notificationPreview: 1}),
    {showBadge: true, desktopNotifications: false, notificationPreview: false});
});

test('image analysis hints follow the URL in the current draft and respect slash commands', () => {
  const context = {kind: 'image', url: 'https://example.test/image.png'};
  assert.ok(imageContextHint(context, `Explain ${context.url}`));
  assert.equal(imageContextHint(context, `  /research ${context.url}`), '');
  assert.equal(imageContextHint(context, 'Explain a different topic'), '');
  assert.equal(imageContextHint({...context, kind: 'page'}, context.url), '');
  assert.equal(imageContextHint({kind: 'image'}, ''), '');
});

test('newly staged images preserve dirty local questions without duplicating URLs', () => {
  const draft = new DraftBuffer();
  const context = {kind: 'image', stageId: 'stage-a', url: 'https://example.test/image.png'};
  draft.edit('Why does this look wrong?');
  draft.mergeImage(context);
  const merged = `Why does this look wrong?\n\nAnalyze this image:\n${context.url}`;
  assert.equal(draft.value, merged);
  assert.equal(draft.dirty, true);
  draft.accept(`Older question\n\nAnalyze this image:\n${context.url}`);
  assert.equal(draft.value, merged, 'A concurrent server snapshot cannot replace the newer local question');
  draft.mergeImage({...context, stageId: 'stage-b'});
  assert.equal(draft.value, merged, 'Restaging the same image does not duplicate its URL');
  draft.accept(merged);
  assert.equal(draft.dirty, false);
  draft.edit('x'.repeat(32000));
  assert.throws(() => draft.mergeImage(context), /too long/i);
  assert.equal(draft.value.length, 32000, 'A failed merge leaves local typing intact');
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
